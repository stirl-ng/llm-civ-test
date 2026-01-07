# Log Flow Comparison: Current vs Desired

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
│ 1. Log to JSONL │───► dll_messages.jsonl
│    (structured) │
│                 │
│ 2. Process      │
│                 │
│ 3. Python log   │───► logs/orchestrator.log
│    (formatted)  │     (shown in UI)
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
│ 1. Log to JSONL │───► dll_messages.jsonl
│    (structured) │     (single source of truth)
│                 │
│ 2. Process      │
│                 │
│ 3. Log tool call │───► dll_messages.jsonl
│    from LLM     │     (direction: "from_llm")
│                 │
│ 4. Query log    │◄─── get_notifications()
│    for LLM      │     get_message_history()
│                 │
│ 5. Log tool     │───► dll_messages.jsonl
│    result       │     (direction: "to_llm")
└────┬────────────┘
     │
     │ HTTP POST /tool
     │ Returns: Same format as log
     ▼
┌─────────┐
│   LLM   │
└─────────┘
     │
     │ Receives: {"type": "notification", "direction": "incoming", ...}
     │ (SAME as log!)
```

**Benefits:**
- Single source of truth (JSONL log)
- LLM receives same messages as log
- UI can show JSONL log
- Full audit trail
- Queryable history

## Message Format Comparison

### Current: Log Entry
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

### Current: LLM Receives
```json
{
  "notifications": [],
  "count": 0,
  "message": "Dummy response - will query DLL directly"
}
```

### Desired: LLM Receives (Same as Log)
```json
{
  "notifications": [
    {
      "type": "notification",
      "direction": "incoming",
      "timestamp": 1234567890.123,
      "turn": 42,
      "player_id": 0,
      "lookup_index": 5,
      "message": "City founded!"
    }
  ],
  "count": 1
}
```

## Tool Call Logging

### Current: Not Logged
- Tool calls from LLM: ❌ Not logged
- Tool results to LLM: ❌ Not logged

### Desired: Full Audit Trail

**Tool Call (from LLM):**
```json
{
  "type": "tool_call",
  "direction": "from_llm",
  "timestamp": 1234567890.123,
  "tool": "get_notifications",
  "arguments": {}
}
```

**Tool Result (to LLM):**
```json
{
  "type": "tool_result_get_notifications",
  "direction": "to_llm",
  "timestamp": 1234567890.124,
  "tool": "get_notifications",
  "result": {
    "notifications": [...],
    "count": 1
  }
}
```

## UI Comparison

### Current: Python Logs
```
[2024-01-01 12:00:00][INFO] 📥 Incoming from DLL: turn_start: {'type': 'turn_start', 'turn': 42, ...}
[2024-01-01 12:00:01][INFO] 🔧 TOOL CALL: get_notifications {}
[2024-01-01 12:00:02][INFO] ✅ TOOL RESULT: get_notifications: {'notifications': [], 'count': 0}
```

### Desired: Structured Messages
```json
{
  "timestamp": 1234567890.123,
  "type": "turn_start",
  "direction": "incoming",
  "turn": 42,
  "player_id": 0,
  "state": {...}
}
```

With filters:
- Type: turn_start | notification | action_result | tool_call | ...
- Direction: incoming | outgoing | from_llm | to_llm
- Turn: ≥ 42
- Player: 0

## Implementation Checklist

- [ ] Update `get_notifications` to use `GameLogger.get_messages()`
- [ ] Add `get_message_history` tool
- [ ] Log tool calls from LLM (`direction: "from_llm"`)
- [ ] Log tool results to LLM (`direction: "to_llm"`)
- [ ] Add `/api/messages` endpoint to dashboard
- [ ] Update dashboard UI to show JSONL messages
- [ ] Add filters: type, direction, turn, player_id
- [ ] Test with real game session
- [ ] Verify LLM receives same format as log
- [ ] Verify UI shows structured messages

