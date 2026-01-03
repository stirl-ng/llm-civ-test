# LLM-Civ Protocol Specification

This document defines the communication protocol between the Civ V DLL, the Orchestrator, and the LLM.

## Architecture Overview

```
┌─────────────────┐         ┌─────────────────────┐         ┌─────────────┐
│    Civ V DLL    │◄──────►│    Orchestrator     │◄───────►│     LLM     │
│                 │  Pipe   │                     │  HTTP    │             │
│  - Game logic   │  JSON   │  - State cache      │  JSON    │  - Queries  │
│  - Execute cmds │         │  - Turn management  │          │  - Decides  │
│  - Send state   │         │  - Protocol bridge  │          │  - Actions  │
└─────────────────┘         └─────────────────────┘         └─────────────┘
```

### Components

| Component | Role |
|-----------|------|
| **DLL** | Runs inside Civ V. Sends game state, executes commands, returns results. |
| **Orchestrator** | Python process. Bridges DLL↔LLM. Manages turns, caches state, handles timeouts. |
| **LLM** | External AI (Claude, GPT, etc). Connects via HTTP, makes decisions using MCP tools. |

### Communication Channels

| Channel | Transport | Format |
|---------|-----------|--------|
| DLL ↔ Orchestrator | Windows Named Pipe | Newline-delimited JSON |
| Orchestrator ↔ LLM | HTTP (localhost) | JSON via REST endpoints |

---

## Turn Lifecycle

### High-Level Flow

```
1. DLL detects it's the LLM player's turn
2. DLL sends `turn_start` message with full game state
3. Orchestrator caches state, opens turn for LLM
4. LLM makes tool calls (queries + actions) via HTTP
   - Query tools: read from orchestrator's cache (fast)
   - Action tools: forwarded to DLL, block until result
5. LLM calls `end_turn` when done
6. Orchestrator sends `end_turn` to DLL
7. DLL acknowledges, advances to next player
```

### Detailed Sequence

```
     DLL                      Orchestrator                      LLM
      │                            │                             │
      │ ───── turn_start ────────► │                             │
      │       {state}              │                             │
      │                            │  [turn now active]          │
      │                            │ ◄──── get_game_state() ──── │
      │                            │ ─────── {state} ──────────► │
      │                            │                             │
      │                            │ ◄──── send_action() ─────── │
      │ ◄─────── action ────────── │       {move unit}           │
      │ ─────── action_result ───► │                             │
      │         {success, delta}   │ ─────── {result} ─────────► │
      │                            │                             │
      │                            │ ◄──── send_action() ─────── │
      │ ◄─────── action ────────── │       {attack}              │
      │ ─────── action_result ───► │                             │
      │         {success, delta}   │ ─────── {result} ─────────► │
      │                            │                             │
      │                            │ ◄──── end_turn() ────────── │
      │ ◄─────── end_turn ──────── │                             │
      │ ─────── turn_end_ack ────► │                             │
      │                            │ ─────── {ended} ──────────► │
      │                            │                             │
      │    [other players turn]    │                             │
      │                            │                             │
      │ ───── turn_start ────────► │  [next turn for LLM]        │
```

---

## DLL ↔ Orchestrator Protocol

Transport: Named pipe (default `\\.\pipe\civv_llm`)
Format: Newline-delimited UTF-8 JSON, one message per line.

### Messages: DLL → Orchestrator

#### `turn_start`
Sent when it becomes the LLM player's turn.

```json
{
  "type": "turn_start",
  "player_id": 0,
  "turn": 42,
  "state": {
    "turn": 42,
    "era": "Classical",
    "gold": 150,
    "science_per_turn": 12,
    "culture_per_turn": 8,
    "cities": [...],
    "units": [...],
    "technologies": {...},
    "diplomacy": {...},
    "resources": {...},
    "pending_decisions": {...}
  }
}
```

#### `action_result`
Sent in response to an action request.

```json
{
  "type": "action_result",
  "request_id": "uuid-1234",
  "success": true,
  "result": {
    "message": "Unit moved successfully",
    "combat": null,
    "promotion_available": false
  },
  "state_delta": {
    "units": [
      {"id": 5, "x": 10, "y": 12, "moves_remaining": 1}
    ],
    "revealed_tiles": [
      {"x": 11, "y": 12, "terrain": "plains", "has_barbarian": true}
    ]
  }
}
```

#### `turn_end_ack`
Acknowledges the turn has ended.

```json
{
  "type": "turn_end_ack",
  "turn": 42,
  "next_turn_eta": null
}
```

### Messages: Orchestrator → DLL

#### `action`
Request to execute a game action.

```json
{
  "type": "action",
  "request_id": "uuid-1234",
  "action": {
    "kind": "move_unit",
    "unit_id": 5,
    "to": [10, 12]
  }
}
```

#### `get_state`
Request a full state refresh.

```json
{
  "type": "get_state",
  "request_id": "uuid-5678"
}
```

#### `end_turn`
Signal that the LLM is done with its turn.

```json
{
  "type": "end_turn"
}
```

---

## Orchestrator ↔ LLM Protocol

Transport: HTTP server on localhost (default port 8765)
Format: JSON request/response

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/state` | Get current cached state |
| GET | `/tools` | List available tools |
| POST | `/tool` | Execute a tool |

### Tool Call Format

**Request:**
```json
POST /tool
{
  "tool": "send_action",
  "arguments": {
    "action": {"kind": "move_unit", "unit_id": 5, "to": [10, 12]}
  }
}
```

**Response:**
```json
{
  "status": "success",
  "result": {
    "success": true,
    "message": "Unit moved",
    "state_delta": {...}
  }
}
```

---

## LLM Tools

### Query Tools (Cache-Only, Fast)

These read from the orchestrator's cached state. No DLL round-trip.

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_game_state` | Full state or filtered by category | `category?`, `format?` |
| `get_cities` | City information | `city_id?` |
| `get_units` | Unit information | `unit_id?` |
| `get_tech_tree` | Technology status | - |
| `get_diplomacy` | Diplomatic relations | - |
| `get_resources` | Strategic/luxury resources | - |
| `get_victory_progress` | Victory condition progress | - |
| `get_available_choices` | Pending decisions | - |
| `format_state` | Human-readable state summary | `raw?` |

### Action Tools (DLL Round-Trip, Blocking)

These send commands to the DLL and wait for results. The orchestrator updates its cached state with the returned `state_delta`.

| Tool | Description | Parameters |
|------|-------------|------------|
| `send_action` | Execute a single game action | `action`, `notes?` |
| `get_state_refresh` | Force full state reload from DLL | - |

### Turn Control Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `end_turn` | Signal done, send all to DLL | `notes?` |

---

## Action Types

Actions sent via `send_action` tool. Each has a `kind` and type-specific parameters.

### Unit Actions

```json
{"kind": "move_unit", "unit_id": 5, "to": [10, 12]}
{"kind": "attack", "unit_id": 5, "target": [11, 12]}
{"kind": "fortify", "unit_id": 5}
{"kind": "sleep", "unit_id": 5}
{"kind": "skip", "unit_id": 5}
{"kind": "delete_unit", "unit_id": 5}
{"kind": "upgrade_unit", "unit_id": 5}
{"kind": "promote_unit", "unit_id": 5, "promotion": "PROMOTION_DRILL_1"}
```

### City Actions

```json
{"kind": "set_production", "city_id": 1, "item": "UNIT_WARRIOR"}
{"kind": "set_production", "city_id": 1, "item": "BUILDING_LIBRARY"}
{"kind": "buy_item", "city_id": 1, "item": "UNIT_SETTLER"}
{"kind": "set_focus", "city_id": 1, "focus": "CITY_AI_FOCUS_TYPE_PRODUCTION"}
{"kind": "sell_building", "city_id": 1, "building": "BUILDING_MONUMENT"}
```

### Research & Culture

```json
{"kind": "set_research", "tech": "TECH_POTTERY"}
{"kind": "adopt_policy", "policy": "POLICY_TRADITION"}
{"kind": "choose_ideology", "ideology": "IDEOLOGY_FREEDOM"}
```

### Diplomacy

```json
{"kind": "declare_war", "target_player": 2}
{"kind": "make_peace", "target_player": 2}
{"kind": "propose_trade", "target_player": 2, "offer": {...}, "demand": {...}}
{"kind": "send_delegate", "city_state": 5}
```

### Great People

```json
{"kind": "use_great_person", "unit_id": 15, "action": "construct_improvement"}
{"kind": "use_great_person", "unit_id": 15, "action": "golden_age"}
```

---

## State Delta Format

When an action is executed, the DLL returns a `state_delta` containing only what changed. The orchestrator merges this into its cached state.

### Delta Structure

```json
{
  "state_delta": {
    "gold": 145,
    "units": [
      {"id": 5, "x": 10, "y": 12, "moves_remaining": 1, "health": 100}
    ],
    "units_removed": [8],
    "cities": [
      {"id": 1, "production_progress": 25}
    ],
    "revealed_tiles": [
      {"x": 11, "y": 12, "terrain": "plains", "feature": null, "resource": "RESOURCE_HORSES"}
    ],
    "notifications": [
      {"type": "combat", "message": "Your Warrior defeated a Barbarian!"}
    ]
  }
}
```

### Merge Rules

1. **Scalars** (gold, turn, etc): Replace with new value
2. **Arrays with IDs** (units, cities): Upsert by ID
3. **Removed items**: Delete by ID from `*_removed` arrays
4. **Revealed tiles**: Append to visibility map
5. **Notifications**: Append (for display to user)

---

## Timeouts & Error Handling

### Timeouts

| Timeout | Default | Description |
|---------|---------|-------------|
| Turn timeout | 300s | Max time for LLM to complete turn |
| Action timeout | 30s | Max time for single DLL action |
| Pipe connect timeout | 30s | Max time to connect to DLL pipe |

### Error Responses

**DLL errors:**
```json
{
  "type": "action_result",
  "request_id": "uuid-1234",
  "success": false,
  "error": {
    "code": "INVALID_UNIT",
    "message": "Unit 5 does not exist"
  },
  "state_delta": null
}
```

**Orchestrator errors (to LLM):**
```json
{
  "status": "error",
  "error": "Action timed out waiting for DLL response"
}
```

### Graceful Degradation

- If DLL disconnects mid-turn: Orchestrator ends turn with whatever actions completed
- If LLM times out: Turn ends with no actions (or partial actions if any queued)
- If action fails: LLM receives error, can retry or skip

---

## Example: Complete Turn

### 1. Turn Starts

DLL sends:
```json
{"type": "turn_start", "player_id": 0, "turn": 1, "state": {"turn": 1, "gold": 100, "cities": [{"id": 1, "name": "Rome", "x": 5, "y": 5}], "units": [{"id": 1, "type": "UNIT_SETTLER", "x": 5, "y": 5}, {"id": 2, "type": "UNIT_WARRIOR", "x": 5, "y": 6}]}}
```

### 2. LLM Queries State

```
POST /tool {"tool": "get_units", "arguments": {}}
→ {"status": "success", "result": {"units": [...], "count": 2}}
```

### 3. LLM Moves Warrior

```
POST /tool {"tool": "send_action", "arguments": {"action": {"kind": "move_unit", "unit_id": 2, "to": [6, 6]}}}
```

Orchestrator → DLL:
```json
{"type": "action", "request_id": "a1", "action": {"kind": "move_unit", "unit_id": 2, "to": [6, 6]}}
```

DLL → Orchestrator:
```json
{"type": "action_result", "request_id": "a1", "success": true, "result": {"message": "Warrior moved"}, "state_delta": {"units": [{"id": 2, "x": 6, "y": 6, "moves_remaining": 1}], "revealed_tiles": [{"x": 7, "y": 6, "terrain": "grassland"}]}}
```

LLM receives:
```json
{"status": "success", "result": {"success": true, "message": "Warrior moved", "state_delta": {...}}}
```

### 4. LLM Founds City

```
POST /tool {"tool": "send_action", "arguments": {"action": {"kind": "found_city", "unit_id": 1}}}
```

### 5. LLM Ends Turn

```
POST /tool {"tool": "end_turn", "arguments": {"notes": "Founded capital, moved warrior to scout"}}
```

Orchestrator → DLL:
```json
{"type": "end_turn"}
```

DLL → Orchestrator:
```json
{"type": "turn_end_ack", "turn": 1}
```

---

## Future: Flask Web UI

A Flask server will provide visibility into the game:

- Real-time game state display
- LLM decision log
- Action history
- Manual override controls

This is separate from the MCP HTTP server and will be documented separately.
