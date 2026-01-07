# Log Parity Summary: Log ↔ LLM ↔ UI

## Current State

### What Gets Logged (dll_messages.jsonl)

**Format:** JSONL (one JSON object per line)

**Incoming Messages (from DLL):**
```json
{
  "type": "turn_start|notification|action_result|trace|pong|...",
  "direction": "incoming",
  "timestamp": 1234567890.123,
  "turn": 42,
  "player_id": 0,
  ...other fields from DLL...
}
```
- Logged in: `pipe_server.py:StateProcessor.process_state()` (line 329)
- All DLL messages are logged with `direction: "incoming"`

**Outgoing Messages (to DLL):**
```json
{
  "type": "research|move|end_turn|ping|...",
  "direction": "outgoing",
  "timestamp": 1234567890.123,
  "request_id": "uuid-string",
  "turn": 42,
  ...action fields...
}
```
- Logged in: `mcp_server.py:_send_action()` (line 447), `_end_turn()` (line 492), `_ping()` (line 694)
- All messages sent to DLL are logged with `direction: "outgoing"`

**Acknowledgments:**
- Separate file: `acknowledgments.jsonl`
- Format: `{"timestamp": float, "notification_id": int, "lookup_index": int}`

### What LLM Receives (via HTTP POST /tool)

**Format:** JSON response

**Current Tool Responses:**
- `get_notifications`: `{"notifications": [], "count": 0, "message": "Dummy response..."}`
- `get_game_state`: `{"message": "Dummy response - state caching removed..."}`
- `send_action`: Returns `action_result` from DLL (matches log format)
- `end_turn`: `{"status": "success|blocked|error", "turn": 42, ...}`
- `ping`: `{"status": "ok", "dll_response": "pong", ...}`

**Issue:** Most tools return dummy responses, NOT the actual messages from the log.

### What UI Shows (Dashboard)

**Format:** Python logging (formatted strings)

**Source:**
- In-memory buffer: `DashboardLogHandler` captures Python log messages
- File: Reads from `logs/orchestrator.log` (formatted log file)

**Display Format:**
```json
{
  "timestamp": "2024-01-01T12:00:00",
  "level": "INFO|DEBUG|WARNING|ERROR",
  "logger": "orchestrator.pipe_server",
  "message": "📥 Incoming from DLL: turn_start: {...}",
  "raw_message": "...",
  "player_id": 0
}
```

**Issue:** UI shows Python logs (formatted strings), NOT the structured JSONL messages.

## Problems

### 1. No Parity: Log ≠ LLM

| Aspect | Log | LLM Receives |
|--------|-----|--------------|
| Notifications | `{"type": "notification", "direction": "incoming", ...}` | `{"notifications": [], "count": 0, "message": "Dummy..."}` |
| Game State | `{"type": "turn_start", "state": {...}}` | `{"message": "Dummy response..."}` |
| Actions | `{"type": "research", "direction": "outgoing", ...}` | `{"status": "success", ...}` (different format) |

### 2. UI Shows Wrong Data

- UI shows Python logging (human-readable strings)
- UI does NOT show JSONL log (structured data)
- UI does NOT show what LLM actually receives
- No way to see the actual message flow

### 3. Missing Integration

- `get_notifications` should use `GameLogger.get_messages()` but returns dummy
- Other query tools should read from log but return dummies
- No tool to query message history
- No way for LLM to see full conversation history

## Recommendations

### Priority 1: Make LLM Receive Log Messages

**Update `get_notifications` to use GameLogger:**
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

**Add `get_message_history` tool:**
```python
{
    "name": "get_message_history",
    "description": "Get message history from the log.",
    "parameters": {
        "message_type": "optional string (e.g., 'turn_start', 'notification')",
        "direction": "optional string: 'incoming'|'outgoing'",
        "min_turn": "optional int",
        "limit": "optional int (default 100)"
    }
}
```

### Priority 2: Update UI to Show JSONL Log

**Add endpoint:**
```python
@app.route("/api/messages")
def api_messages():
    """Get messages from JSONL log."""
    message_type = request.args.get("type")
    direction = request.args.get("direction")
    min_turn = request.args.get("min_turn", type=int)
    limit = int(request.args.get("limit", 100))
    
    messages = game_logger.get_messages(
        message_type=message_type,
        min_turn=min_turn,
        limit=limit
    )
    
    # Filter by direction if specified
    if direction:
        messages = [m for m in messages if m.get("direction") == direction]
    
    return jsonify({"messages": messages, "count": len(messages)})
```

**Update dashboard UI:**
- Add tab/panel for "Message Log" (JSONL)
- Show structured messages with syntax highlighting
- Add filters: type, direction, turn, player_id
- Keep existing "Python Logs" tab for debugging

### Priority 3: Log Tool Call Results

**Log what LLM receives:**
```python
def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = ...  # existing logic
    
    # Log tool result sent to LLM
    log_entry = {
        "type": f"tool_result_{name}",
        "direction": "to_llm",
        "timestamp": datetime.now().timestamp(),
        "tool": name,
        "arguments": arguments,
        "result": result
    }
    self._message_logger.log_message(log_entry)
    
    return result
```

**Log tool calls from LLM:**
```python
def _handle_tool_call(self, request: dict):
    # Log incoming tool call
    log_entry = {
        "type": "tool_call",
        "direction": "from_llm",
        "timestamp": datetime.now().timestamp(),
        "tool": request.get("tool"),
        "arguments": request.get("arguments", {})
    }
    self._message_logger.log_message(log_entry)
    
    # ... execute tool ...
```

## Format Consistency

**Proposed unified format for all messages:**

```json
{
  "timestamp": 1234567890.123,
  "type": "turn_start|notification|action_result|tool_call|tool_result_*|...",
  "direction": "incoming|outgoing|from_llm|to_llm",
  "turn": 42,
  "player_id": 0,
  ...type-specific fields...
}
```

**Directions:**
- `incoming`: From DLL to Orchestrator
- `outgoing`: From Orchestrator to DLL
- `from_llm`: From LLM to Orchestrator (tool calls)
- `to_llm`: From Orchestrator to LLM (tool results)

## Implementation Plan

1. **Phase 1: Fix `get_notifications`**
   - Update to use `GameLogger.get_messages()`
   - Return same format as log entries
   - Test with real notifications

2. **Phase 2: Add `get_message_history` tool**
   - Implement tool in `mcp_server.py`
   - Add to `AVAILABLE_TOOLS`
   - Update dashboard UI to use it

3. **Phase 3: Update Dashboard**
   - Add `/api/messages` endpoint
   - Add "Message Log" panel to UI
   - Add filters and syntax highlighting

4. **Phase 4: Log Tool Calls**
   - Log tool calls from LLM
   - Log tool results to LLM
   - Ensure format consistency

5. **Phase 5: Update Other Tools**
   - Replace dummy responses with log queries
   - Ensure all tools return log-compatible format

## Success Criteria

✅ LLM receives same messages that are in the log  
✅ UI shows JSONL log messages (structured data)  
✅ Full audit trail: DLL ↔ Orchestrator ↔ LLM  
✅ All messages have consistent format  
✅ Can query message history via tools  
✅ Dashboard can filter and display messages

