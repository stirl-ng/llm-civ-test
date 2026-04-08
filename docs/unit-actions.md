# Unit Actions

How to list units and execute unit actions via the LLM agent tools.

---

## Listing Units

Use `get_units` with no arguments. Returns all units for the active player.

**Key response fields:**
- `id` — unit identifier; use this in all action tools
- `x`, `y` — current coordinates
- `unit_type_name` — e.g. `"Settler"`, `"Warrior"`
- `moves_remaining` — movement points left this turn
- `can_move` — whether the unit can still act
- `activity` — if `"MISSION"`, unit is already executing a queued path; do not re-command it

---

## Unit Action Tools

Each action is a first-class tool with flat parameters — no nesting.

### `move_unit`

Move a unit to target coordinates. Supports multi-turn A* pathfinding — give the destination, not the next step.

```json
{ "unit_id": 1001, "to": [16, 21] }
```

**Errors:** `UNIT_NOT_FOUND`, `INVALID_PLOT`, `INVALID_COORDINATES`

---

### `unit_found_city`

Found a city with a settler at its current location. Settler is consumed.

```json
{ "unit_id": 1001 }
```

**Errors:** `UNIT_NOT_FOUND`, `UNIT_NOT_OWNED`, `CANNOT_FOUND_CITY`

---

### `unit_sleep`

Put a unit to sleep indefinitely. Unit stays in place until manually woken.

```json
{ "unit_id": 1002 }
```

---

### `unit_skip`

Skip the unit's turn without sleeping. Use to clear the "unit needs orders" state for one turn.

```json
{ "unit_id": 1002 }
```

---

### `unit_alert`

Set a unit to alert stance. Unit will auto-wake if enemies approach.

```json
{ "unit_id": 1002 }
```

---

### `unit_fortify`

Fortify a unit in place. Unit gains stacking defensive bonuses each turn it remains fortified.

```json
{ "unit_id": 1002 }
```

---

### `unit_heal`

Set a unit to heal. Unit skips movement and recovers HP.

```json
{ "unit_id": 1002 }
```

---

## Typical Turn Flow

1. Call `get_units` — identify units needing orders
2. Skip units with `activity == "MISSION"` (already pathing)
3. For each remaining unit: call the appropriate action tool
4. Call `end_turn` when done

---

## Error Handling

All action tools return `success: true/false`. On failure, an `error` object is included:

```json
{
  "success": false,
  "error": {
    "code": "CANNOT_FOUND_CITY",
    "message": "Unit cannot found a city at this location"
  }
}
```

Common codes: `UNIT_NOT_FOUND`, `UNIT_NOT_OWNED`, `CANNOT_FOUND_CITY`, `INVALID_PLOT`, `INVALID_COORDINATES`

---

## Adding New Unit Actions

1. Add a `msgType` branch in `HandlePipeCommand()` in `CvGame.cpp`
2. Add a handler method and entry in `_TOOLS` in `python/orchestrator/mcp_server.py`
3. Add an OpenAI-format schema in `python/agent_runtime/tools/schemas.py`

Note: `mcp_server._TOOLS` and `schemas.py` must be kept in sync manually — see `docs/systems.md`.
