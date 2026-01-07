# Log Review: Parity Between Log, LLM, and UI

## Current State Analysis

### 1. What Goes to the Log (game_logger.py)

The `GameLogger` class writes to `dll_messages.jsonl`:

**Incoming Messages (from DLL):**
- Logged in `pipe_server.py:StateProcessor.process_state()` (line 329)
- All messages from DLL are logged with `"direction": "incoming"`
- Includes: `turn_start`, `notification`, `game_notification`, `trace`, `action_result`, `pong`, etc.
- Format: Full message dict + `timestamp` + `direction: "incoming"`

**Outgoing Messages (to DLL):**
- Logged in `mcp_server.py`:
  - `_send_action()` (line 447): Actions sent to DLL with `"direction": "outgoing"`
  - `_end_turn()` (line 492): End turn requests with `"direction": "outgoing"`
  - `_ping()` (line 694): Ping messages with `"direction": "outgoing"`
- Format: Full message dict + `timestamp` + `direction: "outgoing"`

**Acknowledgments:**
- Logged to separate `acknowledgments.jsonl` file
- Format: `{"timestamp": float, "notification_id": int, "lookup_index": int}`

### 2. What the LLM Receives

The LLM makes HTTP POST requests to `/tool` and receives JSON responses:

**Tool Call Results:**
- Currently most tools return dummy responses (e.g., `_get_notifications_dummy()`)
- `send_action` returns the DLL response (action_result or error)
- `end_turn` returns status dict
- `ping` returns pong response

**Issue:** The LLM does NOT receive the same messages that are in the log. For example:
- Log has: `{"type": "notification", "direction": "incoming", ...}`
- LLM receives: `{"notifications": [], "count": 0, "message": "Dummy response..."}`

### 3. What the UI Shows (dashboard.py)

The dashboard shows **Python logging** (standard `logging` module), NOT the JSONL game log:

**Dashboard Log Handler:**
- Captures all Python log messages via `DashboardLogHandler`
- Stores in memory buffer (`_log_buffer`)
- Also reads from `logs/orchestrator.log` file
- Format: `{"timestamp": str, "level": str, "logger": str, "message": str, "raw_message": str, "player_id": int}`

**Issue:** The UI shows Python logs (which are formatted strings), not the structured JSONL messages that the LLM should receive.

## Problems Identified

1. **No Parity Between Log and LLM:**
   - Log stores raw DLL messages (structured JSON)
   - LLM receives tool call results (different format, often dummy responses)
   - These are fundamentally different data structures

2. **UI Shows Wrong Data:**
   - UI shows Python logging (formatted strings)
   - UI does NOT show the JSONL game log
   - UI does NOT show what the LLM actually receives

3. **Missing Integration:**
   - `get_notifications` tool should query `GameLogger.get_messages()` but currently returns dummy
   - Other query tools should also use the logger but return dummies
   - No way for LLM to see the full message history from the log

## Recommendations

### Option A: Make LLM Receive Log Messages Directly

1. **Update query tools to read from GameLogger:**
   - `get_notifications` → `GameLogger.get_messages(message_type="notification", unacknowledged_only=True)`
   - `get_game_state` → Could return recent `turn_start` messages
   - Add new tool: `get_message_history(filter)` → Returns messages from log

2. **Format consistency:**
   - Ensure tool responses match the log format (same fields, same structure)
   - Remove dummy responses

### Option B: Make Log Store What LLM Receives

1. **Log tool call results:**
   - After each tool execution, log the result sent to LLM
   - Store in same format as DLL messages

2. **Two-way logging:**
   - Keep DLL messages (incoming/outgoing)
   - Also log LLM tool calls and responses

### Option C: Unified Message Stream (Recommended)

1. **Single source of truth:**
   - All messages (DLL → Orchestrator, Orchestrator → LLM, LLM → Orchestrator, Orchestrator → DLL) go to same log
   - Each message tagged with direction and source

2. **LLM receives from log:**
   - Query tools read from GameLogger
   - Responses match log format exactly

3. **UI shows log:**
   - Dashboard reads from `dll_messages.jsonl`
   - Shows structured JSON messages
   - Can filter by type, direction, turn, etc.

## Proposed Changes

### 1. Update `get_notifications` to use GameLogger

```python
def _get_notifications(self) -> dict[str, Any]:
    """Get unacknowledged notifications from the log."""
    notifications = self._message_logger.get_messages(
        message_type="notification",
        unacknowledged_only=True
    )
    return {
        "notifications": notifications,
        "count": len(notifications)
    }
```

### 2. Add tool to get message history

```python
{
    "name": "get_message_history",
    "description": "Get message history from the log with optional filters.",
    "parameters": {
        "message_type": "optional string",
        "direction": "optional string: 'incoming'|'outgoing'",
        "min_turn": "optional int",
        "limit": "optional int (default 100)"
    }
}
```

### 3. Update dashboard to show JSONL log

- Add endpoint: `GET /api/messages` that reads from `dll_messages.jsonl`
- Update UI to display structured messages
- Add filters for message type, direction, turn

### 4. Log tool call results

- After `execute_tool()`, log the result sent to LLM
- Tag with `"direction": "to_llm"` or similar
- This creates a complete audit trail

## Format Consistency

All messages should follow this structure:

```json
{
  "timestamp": 1234567890.123,
  "type": "notification|turn_start|action_result|...",
  "direction": "incoming|outgoing|to_llm|from_llm",
  "turn": 42,
  "player_id": 0,
  ...other fields...
}
```

This ensures:
- Log entries are structured and queryable
- LLM receives same format
- UI can display consistently
- Full audit trail of all communication

