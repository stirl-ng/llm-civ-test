# Game & Session Tracking Implementation

This document describes the game_id and session_id tracking feature added to enable filtering logs and messages by game session.

---

## Overview

Two new fields are now included in all DLL events and hooks:

| Field | Type | Source | Persists Across Save/Load? |
|-------|------|--------|---------------------------|
| `game_id` | uint | `CvPreGame::mapRandomSeed()` | Yes |
| `session_id` | uint | `GetTickCount()` on pipe connect | No (new on each connection) |

**Use cases:**
- Filter JSONL logs to show only current game
- Detect when a new game starts vs. continuing existing game
- Track connection sessions for debugging

---

## DLL Implementation (COMPLETE)

### Files Modified

1. **`GameStatePipe.h`**
   - Added `unsigned int m_uiSessionId` member variable
   - Added `unsigned int GetSessionId() const` accessor

2. **`GameStatePipe.cpp`**
   - Initialize `m_uiSessionId` to 0 in constructor
   - Generate session ID in `ConnectPipe()`:
     ```cpp
     m_uiSessionId = GetTickCount();
     LogMessage("GameStatePipe: Connected with session_id=%u", m_uiSessionId);
     ```

3. **`CvGame.cpp`** - Added to all outgoing messages:
   ```cpp
   payload << ",\"game_id\":" << CvPreGame::mapRandomSeed();
   payload << ",\"session_id\":" << m_kGameStatePipe.GetSessionId();
   ```

   Functions updated:
   - `SendTurnStartToPipe()`
   - `SendTurnCompleteToPipe()`
   - `SendNotificationToPipe()`
   - `SendPopupToPipe()`
   - `SendDiplomaticMessageToPipe()`
   - `SendTechResearchedToPipe()`

4. **`docs/api.yaml`** - Added `game_id` and `session_id` to:
   - Events: `turn_start`, `turn_complete`
   - Hooks: `notification`, `popup`, `diplomatic_message`, `tech_researched`

5. **`docs/protocol.md`** - Added "Session Tracking" section

---

## Python Orchestrator Implementation (TODO)

### File: `python/orchestrator/pipe_server.py`

**Goal:** Track current game_id and session_id from incoming messages.

```python
class StateProcessor:
    def __init__(self, ...):
        # ... existing code ...

        # Session tracking
        self._current_game_id: Optional[int] = None
        self._current_session_id: Optional[int] = None

    def process_state(self, state: dict) -> None:
        # Extract IDs from turn_start messages
        if state.get("type") == "turn_start":
            new_game_id = state.get("game_id")
            new_session_id = state.get("session_id")

            # Detect game change
            if self._current_game_id is not None and new_game_id != self._current_game_id:
                logger.info(f"New game detected! game_id changed from {self._current_game_id} to {new_game_id}")
                # Optional: Clear in-memory caches, rotate logs, etc.

            # Detect session change (reconnect)
            if self._current_session_id is not None and new_session_id != self._current_session_id:
                logger.info(f"New session detected! session_id changed from {self._current_session_id} to {new_session_id}")

            self._current_game_id = new_game_id
            self._current_session_id = new_session_id

        # ... rest of existing process_state code ...

    @property
    def current_game_id(self) -> Optional[int]:
        """Get the current game ID."""
        return self._current_game_id

    @property
    def current_session_id(self) -> Optional[int]:
        """Get the current session ID."""
        return self._current_session_id
```

### File: `python/orchestrator/game_logger.py`

**Goal:** Add game_id and session_id filtering to `get_messages()`.

```python
def get_messages(
    self,
    message_type: Optional[str] = None,
    turn_number: Optional[int] = None,
    player_id: Optional[int] = None,
    game_id: Optional[int] = None,      # NEW
    session_id: Optional[int] = None,   # NEW
) -> list[dict[str, Any]]:
    """Get messages from the JSONL file.

    Args:
        message_type: Optional message type to filter by
        turn_number: Optional minimum turn number
        player_id: Optional player ID to filter by
        game_id: Optional game ID to filter by (from mapRandomSeed)
        session_id: Optional session ID to filter by

    Returns:
        List of message dictionaries
    """
    # ... existing loading code ...

    # Filter messages
    filtered = []
    for msg in messages:
        # ... existing filters ...

        # Filter by game_id
        if game_id is not None:
            msg_game_id = msg.get("game_id")
            if msg_game_id != game_id:
                continue

        # Filter by session_id
        if session_id is not None:
            msg_session_id = msg.get("session_id")
            if msg_session_id != session_id:
                continue

        filtered.append(msg)

    return filtered
```

### File: `python/orchestrator/dashboard.py`

**Goal:** Add game_id filter to the `/api/messages` endpoint and UI.

```python
@app.route("/api/messages")
def api_messages():
    """Get messages from JSONL log with optional filters."""
    message_type = request.args.get("type")
    direction = request.args.get("direction")
    turn_number = request.args.get("turn_number", type=int)
    game_id = request.args.get("game_id", type=int)        # NEW
    session_id = request.args.get("session_id", type=int)  # NEW
    current_game_only = request.args.get("current_game", type=bool, default=True)  # NEW
    limit = int(request.args.get("limit", 100))

    # If current_game_only and no explicit game_id, use current game
    if current_game_only and game_id is None:
        game_id = state_processor.current_game_id  # Get from StateProcessor

    messages = game_logger.get_messages(
        message_type=message_type,
        turn_number=turn_number,
        game_id=game_id,
        session_id=session_id,
        limit=limit
    )

    # Filter by direction if specified
    if direction:
        messages = [m for m in messages if m.get("direction") == direction]

    return jsonify({
        "messages": messages,
        "count": len(messages),
        "game_id": game_id,
        "session_id": session_id
    })

@app.route("/api/session")
def api_session():
    """Get current game and session info."""
    return jsonify({
        "game_id": state_processor.current_game_id,
        "session_id": state_processor.current_session_id,
        "connected": state_processor.is_connected  # if this exists
    })
```

### File: `python/orchestrator/mcp_server.py`

**Goal:** Optionally expose game_id in tool responses.

```python
def _get_game_state(self) -> dict[str, Any]:
    """Get current game state."""
    return {
        "game_id": self._state_processor.current_game_id,
        "session_id": self._state_processor.current_session_id,
        "turn": self._state_processor.current_turn,
        # ... other state ...
    }
```

---

## Testing Checklist

- [ ] Start game, verify `game_id` and `session_id` appear in turn_start
- [ ] Save and load game, verify `game_id` stays same, `session_id` may change
- [ ] Start new game, verify `game_id` changes
- [ ] Disconnect/reconnect orchestrator, verify `session_id` changes
- [ ] Verify notifications include `game_id` and `session_id`
- [ ] Verify dashboard can filter by current game
- [ ] Verify JSONL log contains both IDs

---

## Message Examples

### turn_start (before)
```json
{
  "type": "turn_start",
  "player_id": 0,
  "turn": 7,
  "player_name": "Augustus Caesar",
  "is_human": true,
  "state": { ... }
}
```

### turn_start (after)
```json
{
  "type": "turn_start",
  "game_id": 1847293654,
  "session_id": 3847561,
  "player_id": 0,
  "turn": 7,
  "player_name": "Augustus Caesar",
  "is_human": true,
  "state": { ... }
}
```

### notification (after)
```json
{
  "type": "notification",
  "game_id": 1847293654,
  "session_id": 3847561,
  "player_id": 0,
  "notification_type": 42,
  "lookup_index": 5,
  "turn": 7,
  "message": "City founded!",
  "summary": "New City"
}
```

---

## Log Filtering Use Cases

### Show only current game's messages
```python
messages = game_logger.get_messages(game_id=current_game_id)
```

### Show only this session's notifications
```python
notifications = game_logger.get_messages(
    message_type="notification",
    session_id=current_session_id
)
```

### Dashboard URL with filter
```
/api/messages?game_id=1847293654&type=notification&limit=50
```

---

## Future Considerations

1. **Log rotation**: When game_id changes, could archive old log file
2. **In-memory cache**: Clear cached state when game_id changes
3. **Separate log files per game**: `dll_messages_{game_id}.jsonl`
4. **Session history**: Track all sessions for a game in a separate file
