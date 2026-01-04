# DLL ↔ Orchestrator Protocol

This document describes all messages exchanged between the Civ V DLL and the Python orchestrator over the named pipe.

**Pipe**: `\\.\pipe\civv_llm` (configurable via `--pipe` flag)
**Format**: Newline-delimited JSON
**Encoding**: UTF-8

---

## Overview

```
┌─────────┐                              ┌──────────────┐
│   DLL   │  ───── turn_start ────────►  │ Orchestrator │
│         │                              │              │
│         │  ◄───── action ───────────   │   (LLM)      │
│         │  ───── action_result ─────►  │              │
│         │                              │              │
│         │  ◄───── action ───────────   │              │
│         │  ───── action_result ─────►  │              │
│         │                              │              │
│         │  ◄───── end_turn ─────────   │              │
│         │                              │              │
│         │  ───── turn_start ────────►  │  (next turn) │
└─────────┘                              └──────────────┘
```

---

## Messages FROM DLL → Orchestrator

### 1. `turn_start`

Sent at the beginning of each turn when it's the LLM player's turn.

```json
{
  "type": "turn_start",
  "player_id": 0,
  "turn": 7,
  "state": {
    "turn": 7,
    "playersAlive": 18,
    "civsEver": 18,
    // ... additional game state fields
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"turn_start"` |
| `player_id` | int | The player ID whose turn it is |
| `turn` | int | Current turn number |
| `state` | object | Full game state snapshot (see State Schema below) |

---

### 2. `action_result`

Sent in response to each action received from the orchestrator.

```json
{
  "type": "action_result",
  "success": true,
  "action": {
    "unit_id": 5,
    "command": "move",
    "x": 10,
    "y": 15
  },
  "result": {
    "moved": true,
    "new_x": 10,
    "new_y": 15,
    "movement_remaining": 1
  },
  "state": {
    // Optional: updated game state after action
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"action_result"` |
| `success` | bool | Whether the action succeeded |
| `action` | object | Echo of the action that was executed |
| `result` | object | Action-specific result data |
| `error` | string | (If `success: false`) Error message |
| `state` | object | (Optional) Updated game state after action |

#### Error Response

```json
{
  "type": "action_result",
  "success": false,
  "action": {
    "unit_id": 5,
    "command": "move",
    "x": 10,
    "y": 15
  },
  "error": "Unit cannot move to that tile - occupied by enemy"
}
```

---

## Messages FROM Orchestrator → DLL

### 1. `action`

Sent when the LLM wants to perform a game action. The orchestrator expects a response before sending another action.

```json
{
  "type": "action",
  "action": {
    // Action-specific fields (see Action Types below)
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"action"` |
| `action` | object | The action to perform |

---

### 2. `end_turn`

Sent when the LLM is done making decisions for this turn.

```json
{
  "type": "end_turn"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"end_turn"` |

**DLL behavior**: After receiving `end_turn`, the DLL should:
1. Advance the game to the next turn
2. When it's the LLM player's turn again, send a new `turn_start`

---

## Action Types

Actions are sent inside the `action` field of an `action` message.

### Unit Movement

```json
{
  "type": "action",
  "action": {
    "command": "move_unit",
    "unit_id": 5,
    "x": 10,
    "y": 15
  }
}
```

### Unit Attack

```json
{
  "type": "action",
  "action": {
    "command": "attack",
    "unit_id": 5,
    "target_x": 11,
    "target_y": 15
  }
}
```

### Research Technology

```json
{
  "type": "action",
  "action": {
    "command": "research",
    "tech": "TECH_POTTERY"
  }
}
```

### City Production

```json
{
  "type": "action",
  "action": {
    "command": "produce",
    "city_id": 1,
    "item": "UNIT_WARRIOR"
  }
}
```

### Adopt Policy

```json
{
  "type": "action",
  "action": {
    "command": "adopt_policy",
    "policy": "POLICY_TRADITION_OPENER"
  }
}
```

### Found City

```json
{
  "type": "action",
  "action": {
    "command": "found_city",
    "unit_id": 3
  }
}
```

### Fortify Unit

```json
{
  "type": "action",
  "action": {
    "command": "fortify",
    "unit_id": 5
  }
}
```

### Skip Unit

```json
{
  "type": "action",
  "action": {
    "command": "skip",
    "unit_id": 5
  }
}
```

### Build Improvement

```json
{
  "type": "action",
  "action": {
    "command": "build",
    "unit_id": 7,
    "improvement": "IMPROVEMENT_FARM"
  }
}
```

---

## State Schema

The `state` object in `turn_start` contains the game state. Suggested structure:

```json
{
  "turn": 7,
  "playersAlive": 18,
  "civsEver": 18,

  "cities": [
    {
      "id": 1,
      "name": "Rome",
      "x": 5,
      "y": 10,
      "population": 3,
      "producing": "UNIT_WARRIOR",
      "turns_remaining": 2,
      "buildings": ["BUILDING_MONUMENT"],
      "available_production": ["UNIT_WARRIOR", "UNIT_SETTLER", "BUILDING_GRANARY"]
    }
  ],

  "units": [
    {
      "id": 5,
      "type": "UNIT_WARRIOR",
      "x": 8,
      "y": 12,
      "health": 100,
      "movement": 2,
      "can_move": true,
      "can_attack": true
    }
  ],

  "technology": {
    "researching": "TECH_POTTERY",
    "turns_remaining": 3,
    "completed": ["TECH_AGRICULTURE", "TECH_MINING"],
    "available": ["TECH_POTTERY", "TECH_ANIMAL_HUSBANDRY", "TECH_ARCHERY"]
  },

  "resources": {
    "gold": 150,
    "gold_per_turn": 5,
    "science_per_turn": 12,
    "culture_per_turn": 3,
    "faith_per_turn": 0
  },

  "diplomacy": {
    "known_civs": ["CIVILIZATION_GREECE", "CIVILIZATION_EGYPT"],
    "at_war_with": [],
    "relationships": {
      "CIVILIZATION_GREECE": "neutral",
      "CIVILIZATION_EGYPT": "friendly"
    }
  }
}
```

---

## Sequence Diagram

```
DLL                                 Orchestrator                          LLM (via HTTP)
 │                                       │                                     │
 │  {"type": "turn_start", ...}          │                                     │
 │ ─────────────────────────────────────►│                                     │
 │                                       │   GET /state                        │
 │                                       │◄────────────────────────────────────│
 │                                       │   {state}                           │
 │                                       │────────────────────────────────────►│
 │                                       │                                     │
 │                                       │   POST /tool send_action            │
 │                                       │◄────────────────────────────────────│
 │  {"type": "action", "action": {...}}  │                                     │
 │◄──────────────────────────────────────│                                     │
 │                                       │                                     │
 │  {"type": "action_result", ...}       │                                     │
 │──────────────────────────────────────►│                                     │
 │                                       │   {action_result}                   │
 │                                       │────────────────────────────────────►│
 │                                       │                                     │
 │                                       │   POST /tool send_action            │
 │                                       │◄────────────────────────────────────│
 │  {"type": "action", "action": {...}}  │                                     │
 │◄──────────────────────────────────────│                                     │
 │  {"type": "action_result", ...}       │                                     │
 │──────────────────────────────────────►│   {action_result}                   │
 │                                       │────────────────────────────────────►│
 │                                       │                                     │
 │                                       │   POST /tool end_turn               │
 │                                       │◄────────────────────────────────────│
 │  {"type": "end_turn"}                 │                                     │
 │◄──────────────────────────────────────│                                     │
 │                                       │   {"status": "turn_ended"}          │
 │                                       │────────────────────────────────────►│
 │                                       │                                     │
 │  (game advances, next turn)           │                                     │
 │                                       │                                     │
 │  {"type": "turn_start", ...}          │                                     │
 │──────────────────────────────────────►│                                     │
 │                                       │                                     │
```

---

## Error Handling

### Invalid JSON from Orchestrator

If the DLL receives invalid JSON, it should respond with:

```json
{
  "type": "error",
  "error": "Invalid JSON",
  "detail": "Unexpected token at position 42"
}
```

### Unknown Action Command

```json
{
  "type": "action_result",
  "success": false,
  "error": "Unknown command: 'fly_to_moon'"
}
```

### Action Not Possible

```json
{
  "type": "action_result",
  "success": false,
  "action": {"command": "move_unit", "unit_id": 5, "x": 10, "y": 15},
  "error": "Unit 5 has no movement points remaining"
}
```

---

## Implementation Notes

1. **Synchronous**: Each action sent by the orchestrator blocks until a response is received
2. **One at a time**: The orchestrator will not send another action until it receives `action_result`
3. **State updates**: The DLL can optionally include updated `state` in `action_result` to keep the LLM informed of changes
4. **Turn advancement**: After `end_turn`, the DLL should process all other players' turns before sending the next `turn_start`
