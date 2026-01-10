# Logging Architecture

Logging strategy for message parity between DLL, LLM, and UI.

---

## Problem Statement

Currently there's no parity between what gets logged, what the LLM receives, and what the UI shows:

| Component | Format | Source |
|-----------|--------|--------|
| **Log** | Structured JSONL | `dll_messages.jsonl` |
| **LLM** | Dummy responses | Tool return values |
| **UI** | Python log strings | `logging` module |

---

## Current Flow

```
┌─────────┐
│   DLL   │
└────┬────┘
     │ turn_start, notifications, action_result
     ▼
┌─────────────────┐
│  Orchestrator   │
│                 │
│ 1. Log to JSONL │───► dll_messages.jsonl (structured)
│                 │
│ 2. Process      │
│                 │
│ 3. Python log   │───► logs/orchestrator.log (strings)
└────┬────────────┘
     │
     │ HTTP POST /tool
     ▼
┌─────────┐
│   LLM   │
└─────────┘
     │
     │ Receives: {"notifications": [], "message": "Dummy..."}
     │ (NOT the same as log!)
```

**Problems:**
- Log has structured JSON messages
- LLM receives dummy/formatted responses
- UI shows Python logs (strings), not JSONL
- No connection between log and LLM
- No audit trail of tool calls

---

## Desired Flow

```
┌─────────┐
│   DLL   │
└────┬────┘
     │ turn_start, notifications, action_result
     ▼
┌─────────────────┐
│  Orchestrator   │
│                 │
│ 1. Log incoming │───► dll_messages.jsonl
│    (from DLL)   │     (direction: "incoming")
│                 │
│ 2. Log tool call│───► dll_messages.jsonl
│    (from LLM)   │     (direction: "outgoing")
│                 │
│ 3. Query log    │◄─── get_notifications()
│    for response │     get_log()
│                 │
│ 4. Log result   │───► dll_messages.jsonl
│    (to LLM)     │     (direction: "incoming")
│                 │
│ 5. Log outgoing │───► dll_messages.jsonl
│    (to DLL)     │     (direction: "outgoing")
└────┬────────────┘
     │
     │ Returns: Same format as log
     ▼
┌─────────┐
│   LLM   │
└─────────┘
     │
     │ Receives: {"type": "notification", ...}
     │ (SAME as log!)
```

**Benefits:**
- Single source of truth (JSONL log)
- LLM receives same messages as log
- UI can show JSONL log with filters
- Full audit trail of all communication
- Queryable history

---

## Message Format

### Unified Structure

All messages follow this format:

```json
{
  "timestamp": 1234567890.123,
  "type": "turn_start|notification|action_result|tool_call|...",
  "direction": "incoming|outgoing",
  "turn": 42,
  "player_id": 0,
  ...type-specific fields...
}
```

### Direction Values

| Direction | Meaning |
|-----------|---------|
| `incoming` | DLL → Orchestrator, Orchestrator → LLM (tool results) |
| `outgoing` | Orchestrator → DLL, LLM → Orchestrator (tool calls) |

### Examples

**Incoming (from DLL):**
```json
{
  "type": "notification",
  "direction": "incoming",
  "timestamp": 1234567890.123,
  "turn": 42,
  "player_id": 0,
  "lookup_index": 5,
  "message": "City founded!"
}
```

**Tool Call (from LLM):**
```json
{
  "type": "tool_call",
  "direction": "outgoing",
  "timestamp": 1234567890.123,
  "tool": "get_notifications",
  "arguments": {}
}
```

**Tool Result (to LLM):**
```json
{
  "type": "tool_result",
  "direction": "incoming",
  "timestamp": 1234567890.124,
  "tool": "get_notifications",
  "result": {
    "notifications": [...],
    "count": 1
  }
}
```

**Outgoing (to DLL):**
```json
{
  "type": "move_unit",
  "direction": "outgoing",
  "timestamp": 1234567890.125,
  "request_id": "uuid-string",
  "unit_id": 5,
  "to": [10, 15]
}
```

---

## Current Logging Points

| Location | What's Logged | Direction |
|----------|---------------|-----------|
| `pipe_server.py:StateProcessor.process_state()` | All DLL messages | `incoming` |
| `mcp_server.py:_send_action()` | Actions to DLL | `outgoing` |
| `mcp_server.py:_end_turn()` | End turn requests | `outgoing` |
| `mcp_server.py:_ping()` | Ping messages | `outgoing` |

**Missing:**
- Tool calls from LLM (`outgoing`)
- Tool results to LLM (`incoming`)

---

## Implementation Plan

### Phase 1: Fix Query Tools

Update `get_notifications` to use GameLogger:

```python
def _get_notifications(self) -> dict[str, Any]:
    """Get unacknowledged notifications from the log."""
    notifications = self._message_logger.get_messages(
        message_type="notification",
        unacknowledged_only=True
    )
    return {
        "notifications": notifications,  # Same format as log
        "count": len(notifications)
    }
```

### Phase 2: Add Message History Tool

```python
{
    "name": "get_log",
    "description": "Get message history from the log.",
    "parameters": {
        "message_type": "optional string",
        "direction": "optional string",
        "turn_number": "optional int",
        "limit": "optional int (default 100)"
    }
}
```

### Phase 3: Log Tool Calls

Log incoming tool calls:
```python
def _handle_tool_call(self, request: dict):
    self._message_logger.log_message({
        "type": "tool_call",
        "direction": "outgoing",
        "timestamp": time.time(),
        "tool": request.get("tool"),
        "arguments": request.get("arguments", {})
    })
```

Log outgoing tool results:
```python
def execute_tool(self, name: str, arguments: dict) -> dict:
    result = ...  # existing logic

    self._message_logger.log_message({
        "type": "tool_result",
        "direction": "incoming",
        "timestamp": time.time(),
        "tool": name,
        "result": result
    })

    return result
```

### Phase 4: Update Dashboard

Add endpoint for JSONL log:
```python
@app.route("/api/messages")
def api_messages():
    message_type = request.args.get("type")
    direction = request.args.get("direction")
    turn_number = request.args.get("turn_number", type=int)
    limit = int(request.args.get("limit", 100))

    messages = game_logger.get_messages(
        message_type=message_type,
        turn_number=turn_number,
        limit=limit
    )

    if direction:
        messages = [m for m in messages if m.get("direction") == direction]

    return jsonify({"messages": messages, "count": len(messages)})
```

Update UI:
- Add "Message Log" panel showing JSONL
- Add filters: type, direction, turn, player_id
- Keep existing "Python Logs" for debugging

---

## Success Criteria

- [ ] LLM receives same messages that are in the log
- [ ] UI shows JSONL log messages (structured data)
- [ ] Full audit trail: DLL ↔ Orchestrator ↔ LLM
- [ ] All messages have consistent format
- [ ] Can query message history via tools
- [ ] Dashboard can filter and display messages
