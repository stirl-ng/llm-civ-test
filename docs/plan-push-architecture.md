# Plan: Push Architecture (SSE + Dashboard SSE)

## Overview

Replace all polling with push. Two separate problems:

| Component | Current | Target |
|---|---|---|
| Agent runner (`run.py`) | `GET /status` every 2s | Subscribe to `GET /events` SSE on orchestrator |
| Dashboard (`dashboard.py`) | `setInterval(refreshData, 5000)` | `EventSource` on `GET /api/stream` SSE in Flask |

**Key finding**: The dashboard is a *separate Flask process* (port 5000) that reads JSONL log files.
It has no connection to the orchestrator at all. SSE (server→client only) is the right transport for both — WebSocket is overkill.

---

## Part A — Agent Runner SSE

### Files to change

| File | Change |
|---|---|
| `python/orchestrator/event_broadcaster.py` | **New** — thread-safe pub/sub |
| `python/orchestrator/pipe_server.py` | Emit events on `turn_start` / disconnect |
| `python/orchestrator/mcp_http_server.py` | Add `GET /events` SSE endpoint |
| `python/orchestrator/__main__.py` | Wire broadcaster into both |
| `python/experiments/run.py` | Replace polling loop with SSE listener |

### Step 1 — `orchestrator/event_broadcaster.py` (new file)

```python
import queue
import threading
from typing import Optional


class EventBroadcaster:
    """Thread-safe pub/sub bus. Each subscriber gets a Queue of event dicts."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: list[tuple[queue.Queue, Optional[int]]] = []

    def subscribe(self, player_id: Optional[int] = None) -> queue.Queue:
        """Register subscriber. player_id=None means receive all events."""
        q = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.append((q, player_id))
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers = [(s, p) for s, p in self._subscribers if s is not q]

    def emit(self, event_type: str, data: dict) -> None:
        payload = {"event": event_type, **data}
        player_id = data.get("player_id")
        with self._lock:
            for q, filter_id in self._subscribers:
                if filter_id is None or filter_id == player_id:
                    try:
                        q.put_nowait(payload)
                    except queue.Full:
                        pass  # drop slow clients
```

**Multi-player extension path**: runners call `subscribe(player_id=N)` to receive only their events. No structural change needed.

### Step 2 — `orchestrator/pipe_server.py`

Add `broadcaster: Optional[EventBroadcaster] = None` to `NamedPipeServer.__init__`.

In `_process_message()`, after `game_state.update_from_message()`:

```python
if msg_type == "turn_start" and self._broadcaster:
    self._broadcaster.emit("turn_start", {
        "turn":        message.get("turn"),
        "game_id":     message.get("game_id"),
        "player_id":   message.get("player_id"),
        "player_name": message.get("player_name"),
    })
```

In `_close()`, after resetting game state:

```python
if self._broadcaster:
    self._broadcaster.emit("disconnected", {})
```

### Step 3 — `orchestrator/mcp_http_server.py`

Add `broadcaster: Optional[EventBroadcaster] = None` to `MCPHTTPServer.__init__`.
Pass to `MCPHTTPHandler` via class attribute (same pattern as `mcp_server`).

Add to `do_GET()`:

```python
elif self.path == "/events":
    self._handle_sse()
```

New method on `MCPHTTPHandler`:

```python
def _handle_sse(self):
    if not self.broadcaster:
        self._send_error(503, "SSE not available")
        return

    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.send_header("Connection", "keep-alive")
    self._send_cors_headers()
    self.end_headers()

    q = self.broadcaster.subscribe()
    try:
        while True:
            try:
                event = q.get(timeout=30)
            except queue.Empty:
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                continue
            event_type = event.get("event", "message")
            data = json.dumps(event)
            self.wfile.write(f"event: {event_type}\ndata: {data}\n\n".encode())
            self.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        self.broadcaster.unsubscribe(q)
```

Ensure `HTTPServer` is `ThreadingHTTPServer` so SSE connections don't block other requests:

```python
from http.server import ThreadingHTTPServer
self.http_server = ThreadingHTTPServer((self.host, self.port), MCPHTTPHandler)
```

### Step 4 — `orchestrator/__main__.py`

```python
from .event_broadcaster import EventBroadcaster

broadcaster = EventBroadcaster()
pipe_server = NamedPipeServer(pipe_name, game_state, broadcaster=broadcaster)
http_server = MCPHTTPServer(host, port, mcp_server, broadcaster=broadcaster)
```

### Step 5 — `experiments/run.py`

Replace `run_game_loop()`. No new dependencies — parse SSE manually from `iter_lines()`.

```python
def run_game_loop(model, base_url: str, poll_interval: float = 2.0,
                  turn_timeout: float | None = None, interactive: bool = False):
    """Main loop: subscribe to SSE turn events, run each turn.

    poll_interval kept for backward compatibility but no longer used.
    """
    last_game_id = None

    while True:  # reconnect loop
        if not check_health(base_url):
            print("Waiting for orchestrator...")
            time.sleep(2)
            continue

        print("Connecting to event stream...")
        try:
            resp = requests.get(f"{base_url}/events", stream=True, timeout=(10, None))
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"SSE connect failed: {e}. Retrying in 2s...")
            time.sleep(2)
            continue

        print("Subscribed. Waiting for turns.")
        event_type = None

        try:
            for raw in resp.iter_lines(chunk_size=1):
                line = raw.decode() if isinstance(raw, bytes) else raw
                if not line:
                    event_type = None
                    continue
                if line.startswith(":"):
                    continue  # keepalive comment
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:") and event_type == "turn_start":
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue

                    current_turn = event.get("turn")
                    current_game_id = event.get("game_id")
                    player_name = event.get("player_name")

                    if last_game_id is not None and current_game_id != last_game_id:
                        print(f"\nNEW GAME ({last_game_id} → {current_game_id})")
                    last_game_id = current_game_id

                    if _message_logger:
                        _message_logger.set_turn(current_turn, current_game_id)

                    print(f"\n{'='*50}\nTURN {current_turn} (game_id: {current_game_id})\n{'='*50}")
                    result = run_turn(model, base_url, current_turn,
                                     game_id=current_game_id,
                                     player_name=player_name,
                                     timeout=turn_timeout,
                                     interactive=interactive)
                    print(f"\nSummary: {result['iterations']} iterations, {result['tool_calls']} tool calls")

        except KeyboardInterrupt:
            raise
        except requests.exceptions.RequestException as e:
            print(f"SSE stream lost: {e}. Reconnecting in 2s...")
            time.sleep(2)
```

The `run_turn()` end-turn wait loop (polls `/status` for up to 10s) is unchanged.

---

## Part B — Dashboard SSE

### Key findings

- Dashboard is a **separate Flask process** (port 5000), reads JSONL log files on every request.
- `GET /api/data` re-parses all logs and returns: `connected`, `current_turn`, `total_tokens`,
  `total_requests`, `estimated_cost`, conversation messages, tool calls, events.
- JS calls `fetch('/api/data')` in `setInterval(refreshData, 5000)`.

The correct push model: **server-side file mtime watch + SSE**. No new library needed.

### Files to change

| File | Change |
|---|---|
| `python/orchestrator/dashboard.py` | Add `GET /api/stream` SSE endpoint; replace JS `setInterval` with `EventSource` |

### Step 1 — Add `/api/stream` endpoint

```python
import time as _time  # avoid shadowing

@app.route("/api/stream")
def api_stream():
    """SSE stream: push fresh data whenever log files change."""
    debug_mode = request.args.get("debug") == "1"
    verbose_mode = request.args.get("verbose") == "1"
    game_id_str = request.args.get("game_id")
    game_id = int(game_id_str) if game_id_str else None

    def generate():
        last_mtime = _log_mtime(game_id)
        data = parse_logs(debug_mode=debug_mode, verbose_mode=verbose_mode, game_id=game_id)
        yield f"event: update\ndata: {json.dumps(data)}\n\n"
        while True:
            _time.sleep(0.5)
            mtime = _log_mtime(game_id)
            if mtime != last_mtime:
                last_mtime = mtime
                data = parse_logs(debug_mode=debug_mode, verbose_mode=verbose_mode, game_id=game_id)
                yield f"event: update\ndata: {json.dumps(data)}\n\n"
            else:
                yield ": keepalive\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _log_mtime(game_id=None) -> float:
    if not LOG_DIR.exists():
        return 0.0
    if game_id:
        f = LOG_DIR / f"game_{game_id}.jsonl"
        return f.stat().st_mtime if f.exists() else 0.0
    files = list(LOG_DIR.glob("game_*.jsonl"))
    return max((f.stat().st_mtime for f in files), default=0.0)
```

### Step 2 — Replace JS polling with `EventSource`

In `TEMPLATE`, replace:

```javascript
refreshInterval = setInterval(refreshData, 5000);
```

With:

```javascript
const params = new URLSearchParams(window.location.search);
const evtSource = new EventSource('/api/stream?' + params.toString());

evtSource.addEventListener('update', (e) => {
    if (isModalOpen()) return;
    try {
        const data = JSON.parse(e.data);
        updateHeader(data);
        updateStats(data);
        updateConversation(data);
        updateToolCalls(data);
        updateRightPanel(data);
        if (data.debug_mode && data.debug) updateDebugPanel(data);
    } catch (err) {
        console.error('SSE parse error:', err);
    }
});

evtSource.onerror = () => {
    console.warn('SSE connection lost, browser will auto-reconnect...');
};
```

Remove the `refreshInterval` variable and `setInterval` call.

Fix Flask startup to support streaming:

```python
app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, use_reloader=False)
```

---

## Verification

### Part A
1. `python -m orchestrator` — start orchestrator
2. `curl -N http://localhost:8765/events` — see `: keepalive` every 30s
3. Start Civ V / begin turn → `turn_start` event appears in curl immediately
4. Run agent → wakes on turn event, no 2s lag visible

### Part B
1. `python -m orchestrator.dashboard`
2. DevTools → Network → filter EventStream → see `/api/stream` with `update` events
3. No repeated XHR to `/api/data` every 5s

---

## Notes
- `/status` endpoint kept — used by `run_turn()` end-turn poll and dashboard header init
- `poll_interval` config key kept but ignored by new agent loop; marked deprecated in YAML
- For simultaneous multiplayer: `subscribe(player_id=N)` + `GET /events?player_id=N` is the extension; no structural change to broadcaster
