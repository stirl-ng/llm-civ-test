# Unit Actions Guide

This guide explains how to list units and execute unit actions in Civilization V via the LLM orchestrator.

## Table of Contents

1. [Listing Units](#listing-units)
2. [Unit Actions](#unit-actions)
3. [Complete Example: Settler on Turn 0](#complete-example-settler-on-turn-0)

---

## Listing Units

### Using the `get_units` Tool

To list all units for the active player, use the `get_units` tool:

```json
{
  "tool": "get_units",
  "arguments": {}
}
```

**Response:**
```json
{
  "type": "units_result",
  "request_id": "...",
  "player_id": 0,
  "turn": 0,
  "units": [
    {
      "id": 1001,
      "x": 15,
      "y": 21,
      "unit_type": 0,
      "unit_type_name": "Settler",
      "moves_remaining": 120,
      "max_moves": 120,
      "damage": 0,
      "max_hit_points": 100,
      "experience": 0,
      "level": 1,
      "can_move": true,
      "is_combat_unit": false,
      "plot": {
        "terrain_type": 1,
        "feature_type": 1
      }
    },
    {
      "id": 1002,
      "x": 15,
      "y": 22,
      "unit_type": 83,
      "unit_type_name": "Warrior",
      "moves_remaining": 120,
      "max_moves": 120,
      "damage": 0,
      "max_hit_points": 100,
      "experience": 0,
      "level": 1,
      "can_move": true,
      "is_combat_unit": true,
      "plot": {
        "terrain_type": 0,
        "feature_type": -1
      }
    }
  ]
}
```

**Key Fields:**
- `id`: Unique unit identifier (use this for actions)
- `x`, `y`: Current coordinates
- `unit_type_name`: Human-readable unit type (e.g., "Settler", "Warrior")
- `moves_remaining`: Movement points left this turn
- `can_move`: Whether the unit can move this turn
- `is_combat_unit`: Whether this is a combat unit

---

## Unit Actions

All unit actions are sent via the `send_action` tool with an action object containing a `kind` field.

### 1. Move Unit

Move a unit to target coordinates.

**Action:**
```json
{
  "tool": "send_action",
  "arguments": {
    "action": {
      "kind": "move_unit",
      "unit_id": 1001,
      "to": [16, 21]
    }
  }
}
```

**Response:**
```json
{
  "type": "move_unit_result",
  "request_id": "...",
  "success": true,
  "result": {
    "message": "Unit moved"
  },
  "state_delta": {
    "units": [
      {
        "id": 1001,
        "x": 16,
        "y": 21,
        "moves_remaining": 60
      }
    ]
  }
}
```

**Errors:**
- `UNIT_NOT_FOUND`: Unit ID doesn't exist
- `INVALID_PLOT`: Target coordinates are invalid
- `INVALID_COORDINATES`: Missing or malformed `to` array

---

### 2. Found City

Found a city with a settler unit at its current location.

**Action:**
```json
{
  "tool": "send_action",
  "arguments": {
    "action": {
      "kind": "unit_found_city",
      "unit_id": 1001
    }
  }
}
```

**Response:**
```json
{
  "type": "unit_found_city_result",
  "request_id": "...",
  "success": true,
  "result": {
    "message": "City founded"
  },
  "state_delta": {
    "unit_id": 1001,
    "x": 15,
    "y": 21
  }
}
```

**Errors:**
- `UNIT_NOT_FOUND`: Unit ID doesn't exist
- `UNIT_NOT_OWNED`: Unit doesn't belong to active player
- `CANNOT_FOUND_CITY`: Unit cannot found a city at this location (too close to another city, invalid terrain, etc.)

**Note:** The settler unit is consumed when founding a city.

---

### 3. Sleep/Fortify

Set a unit to sleep/fortify (defensive stance). The unit will remain in place and gain defensive bonuses.

**Action:**
```json
{
  "tool": "send_action",
  "arguments": {
    "action": {
      "kind": "unit_sleep",
      "unit_id": 1002
    }
  }
}
```

**Response:**
```json
{
  "type": "unit_sleep_result",
  "request_id": "...",
  "success": true,
  "result": {
    "message": "Unit set to sleep/fortify"
  },
  "state_delta": {
    "unit_id": 1002,
    "activity": "sleep"
  }
}
```

**Errors:**
- `UNIT_NOT_FOUND`: Unit ID doesn't exist
- `UNIT_NOT_OWNED`: Unit doesn't belong to active player

---

### 4. Skip/Hold

Set a unit to skip/hold (skip turn without fortifying). The unit will remain in place but won't gain defensive bonuses.

**Action:**
```json
{
  "tool": "send_action",
  "arguments": {
    "action": {
      "kind": "unit_skip",
      "unit_id": 1002
    }
  }
}
```

**Response:**
```json
{
  "type": "unit_skip_result",
  "request_id": "...",
  "success": true,
  "result": {
    "message": "Unit set to skip/hold"
  },
  "state_delta": {
    "unit_id": 1002,
    "activity": "skip"
  }
}
```

**Errors:**
- `UNIT_NOT_FOUND`: Unit ID doesn't exist
- `UNIT_NOT_OWNED`: Unit doesn't belong to active player

---

## Complete Example: Settler on Turn 0

Here's a complete example workflow for handling a settler on turn 0:

### Step 1: List Units

```json
{
  "tool": "get_units",
  "arguments": {}
}
```

**Result:** Find the settler (e.g., unit ID 1001 at coordinates [15, 21])

### Step 2: Choose an Action

#### Option A: Move the Settler

```json
{
  "tool": "send_action",
  "arguments": {
    "action": {
      "kind": "move_unit",
      "unit_id": 1001,
      "to": [16, 21]
    }
  }
}
```

#### Option B: Found City at Current Location

```json
{
  "tool": "send_action",
  "arguments": {
    "action": {
      "kind": "unit_found_city",
      "unit_id": 1001
    }
  }
}
```

#### Option C: Sleep/Fortify (Wait)

```json
{
  "tool": "send_action",
  "arguments": {
    "action": {
      "kind": "unit_sleep",
      "unit_id": 1001
    }
  }
}
```

#### Option D: Skip Turn

```json
{
  "tool": "send_action",
  "arguments": {
    "action": {
      "kind": "unit_skip",
      "unit_id": 1001
    }
  }
}
```

### Step 3: End Turn

After all actions are complete:

```json
{
  "tool": "end_turn",
  "arguments": {
    "turn": 0
  }
}
```

---

## Action Design Pattern

All unit actions follow this pattern:

1. **Query state** using `get_units` to find unit IDs and positions
2. **Execute action** using `send_action` with:
   - `kind`: Action type (`move_unit`, `unit_found_city`, `unit_sleep`, `unit_skip`)
   - `unit_id`: Unit identifier from `get_units`
   - Additional fields as needed (e.g., `to` for `move_unit`)
3. **Check response** for `success` and handle errors
4. **Repeat** for additional units/actions
5. **End turn** when done

---

## Extending to Other Actions

The system is designed to be easily extensible. To add new unit actions:

1. **Add DLL handler** in `CvGame.cpp` (after `select_unit` handler)
2. **Update API docs** in `docs/api.yaml`
3. **Use via `send_action`** with the new `kind` value

The MCP server automatically routes any action `kind` to the DLL, so no Python changes are needed for new action types.

---

## Error Handling

All actions return structured error responses:

```json
{
  "type": "unit_found_city_result",
  "request_id": "...",
  "success": false,
  "error": {
    "code": "CANNOT_FOUND_CITY",
    "message": "Unit cannot found a city at this location"
  }
}
```

Common error codes:
- `UNIT_NOT_FOUND`: Invalid unit ID
- `UNIT_NOT_OWNED`: Unit belongs to another player
- `CANNOT_FOUND_CITY`: City founding requirements not met
- `INVALID_PLOT`: Invalid coordinates
- `INVALID_COORDINATES`: Malformed coordinate array

Always check the `success` field before proceeding.

