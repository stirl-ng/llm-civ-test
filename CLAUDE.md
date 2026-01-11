# Claude Code Conventions for LLM-Civ Integration

This document establishes patterns and conventions for the LLM pipe integration in this Civ V mod.

## Architecture Overview

The LLM integration uses a named pipe (`\\.\pipe\civv_llm`) for bidirectional communication:
- **C++ (DLL)**: Handles pipe connection, sends game events, processes commands
- **Lua (UI)**: Auto-closes popups, sends choice options to pipe (for now)
- **Python (Orchestrator)**: MCP server that bridges the game to LLM tools

## Key Convention: Prefer C++ for Pipe Messaging

**IMPORTANT**: When adding new pipe messaging, prefer implementing in C++ rather than Lua.

### Why C++ over Lua:
1. **Single implementation** - C++ code exists once, Lua popups often have 4+ variants
2. **No JSON helper duplication** - C++ has `PipeJson::Escape()` already
3. **Centralized logic** - All pipe handling in `CvGame.cpp` and `GameStatePipe.cpp`
4. **Type safety** - C++ catches errors at compile time

### When Lua pipe messaging is acceptable:
- Choice popups where Lua knows the available options (TechPopup, ProductionPopup, etc.)
- These still use `Game.SendPipeMessage(json)` which routes through C++

### When to use C++ pipe messaging:
- Informational popups (game start, new era, etc.) - just auto-close in Lua
- Game events (turn start, turn complete, notifications)
- Command responses (tech selected, production set, etc.)

## Popup Patterns

### 1. Informational Popups (No Choices)
Examples: NewEraPopup, NaturalWonderPopup, TechAwardPopup, LoadScreen (Dawn of Man)

**Pattern**: Timer-based auto-close in Lua, any info sent from C++

```lua
-- Standard timer variables
local g_autoCloseTimer = 0
local AUTO_CLOSE_SECONDS = 2.0  -- Use this name consistently!

-- In SetUpdate handler
ContextPtr:SetUpdate(function(fDTime)
    if not ContextPtr:IsHidden() then
        g_autoCloseTimer = g_autoCloseTimer + fDTime
        if g_autoCloseTimer >= AUTO_CLOSE_SECONDS then
            g_autoCloseTimer = 0
            OnClose()
        end
    end
end)

-- Reset timer when popup opens
g_autoCloseTimer = 0
```

### 2. Choice Popups (Requires Selection)
Examples: TechPopup, ProductionPopup, ChooseReligionPopup, ChoosePantheonPopup

**Pattern**: State-based auto-close in Lua, sends options via pipe

```lua
-- Track initial state when popup opens
local g_initialState = nil

-- On popup open
g_initialState = GetCurrentState()
SendChoicesToPipe()  -- Lua sends available options

-- In SetUpdate handler - close when state changes
ContextPtr:SetUpdate(function(fDTime)
    if not ContextPtr:IsHidden() then
        local currentState = GetCurrentState()
        if currentState ~= g_initialState then
            ClosePopup()
        end
    end
end)
```

## C++ Pipe Functions (CvGame.cpp)

### Sending Messages
```cpp
// Use existing pattern in CvGame.cpp
void CvGame::SendXxxToPipe()
{
    if (!m_kGameStatePipe.IsRunning())
        return;

    std::ostringstream payload;
    payload << "{\"type\":\"xxx\"";
    payload << ",\"game_id\":" << CvPreGame::mapRandomSeed();
    payload << ",\"session_id\":" << m_kGameStatePipe.GetSessionId();
    // ... add fields
    payload << "}";

    m_kGameStatePipe.SendMessage(payload.str());
}
```

### Handling Commands
Commands are handled in `CvGame::HandlePipeCommand()`. Add new command handlers there:
```cpp
else if (msgType == "your_command")
{
    // Parse parameters with PipeJson::GetInt(), PipeJson::GetString()
    // Execute game action
    // Send response via SendRawMessageToPipe()
}
```

## MCP Tools (mcp_server.py)

When adding new tools:
1. Add tool definition to `TOOL_DEFINITIONS` dict
2. Implement handler method `_your_tool()`
3. Handler sends command to pipe, waits for response

## File Locations

- **C++ Pipe Logic**: `CvGameCoreDLL_Expansion2/GameStatePipe.cpp`, `CvGame.cpp`
- **Lua Popups**: `(1) Community Patch/LUA/`, `(1) Community Patch/Core Files/Overrides/`
- **MCP Server**: `python/orchestrator/mcp_server.py`

## Current Known Duplication

The following Lua files have duplicated `JsonEncode()`/`JsonEncodeArray()` helpers:
- TechPopup.lua
- ProductionPopup.lua
- ChooseReligionPopup.lua
- ChoosePantheonPopup.lua
- DeclareWarPopup.lua (city capture popup)

This is accepted technical debt. Future improvement: create shared include or move to C++.

## Naming Conventions

- Timer constants: `AUTO_CLOSE_SECONDS` (not `AUTO_CLOSE_DELAY`)
- Timer variables: `g_autoCloseTimer`
- Initial state tracking: `g_initialXxx` (e.g., `g_initialResearch`, `g_initialProductionItem`)

---

## Documentation References

### Primary Documentation (`./docs/`)

| Document | Purpose | Key Content |
|----------|---------|-------------|
| **[protocol.md](docs/protocol.md)** | Protocol specification | Message format, architecture diagrams, session tracking |
| **[api.yaml](docs/api.yaml)** | Full API specification | All commands, events, popup hooks with parameters |
| **[state-schema.md](docs/state-schema.md)** | Game state reference | 20 categories of queryable state (cities, units, diplomacy, etc.) |
| **[orchestrator.md](docs/orchestrator.md)** | Python orchestrator | CLI options, HTTP endpoints, turn flow |
| **[getting-started.md](docs/getting-started.md)** | Quick start guide | Setup, curl examples, troubleshooting |
| **[unit-actions.md](docs/unit-actions.md)** | Unit action guide | move_unit, unit_found_city, unit_sleep, unit_skip |
| **[logging.md](docs/logging.md)** | Logging architecture | Message parity between DLL, LLM, and UI |

### Key Protocol Details (from `docs/protocol.md`)

- **Pipe name**: `\\.\pipe\civv_llm`
- **Session tracking**: `game_id` (map seed, persists across saves) + `session_id` (per connection)
- **Message types**: `turn_start`, `turn_complete`, `notification`, `popup_choice_needed`, `heartbeat`
- **Command flow**: LLM → HTTP → Orchestrator → Pipe → DLL → Response → LLM

### API Reference (from `docs/api.yaml`)

**Core Commands:**
- `research` - Set research target (`tech` parameter)
- `set_production` - Set city production (`city_id`, `item_type`, `item_id`)
- `move_unit` - Move unit to coordinates (`unit_id`, `to: [x, y]`)
- `unit_found_city` - Found city with settler (`unit_id`)
- `end_turn` - End current turn (requires `turn` parameter for validation)

**Popup Hooks:**
- `choose_tech` - Technology selection popup (TechPopup.lua)
- `choose_production` - City production popup (ProductionPopup.lua)
- `choose_pantheon` - Pantheon belief selection (ChoosePantheonPopup.lua)
- `choose_religion` - Religion founding/enhancing (ChooseReligionPopup.lua)
- `city_captured` - Annex/puppet/raze decision (DeclareWarPopup.lua)

---

## Key C++ Files and Methods

### GameStatePipe.cpp
**Purpose**: Manages the named pipe connection and message routing

| Method | Description |
|--------|-------------|
| `Start()` | Creates named pipe, starts worker thread |
| `SendMessage()` | Queue message for sending to orchestrator |
| `GetSessionId()` | Returns current session ID |
| `IsRunning()` | Check if pipe is connected |

### CvGame.cpp - Pipe Integration Methods
**Purpose**: High-level game state and event messaging

| Method | Description |
|--------|-------------|
| `SendTurnStartToPipe()` | Sends full game state at turn start |
| `SendTurnCompleteToPipe()` | Signals turn end |
| `SendGameStartInfoToPipe()` | Sends civilization/leader info (Dawn of Man) |
| `SendHeartbeatToPipe()` | Periodic connection check |
| `HandlePipeCommand()` | Routes incoming commands to handlers |

### CvGame.cpp - Command Handlers (in `HandlePipeCommand`)
Commands are routed by `type` field:

| Command Type | Handler Logic |
|--------------|---------------|
| `research` | `GET_TEAM().SetResearch()` |
| `set_production` | `pCity->pushOrder()` |
| `move_unit` | `pUnit->PushMission()` |
| `unit_found_city` | `pUnit->PushMission(CvTypes::getMISSION_FOUND())` |
| `unit_sleep` | `pUnit->PushMission(CvTypes::getMISSION_SLEEP())` |
| `select_unit` | `CvInterfacePtr->selectUnit()` |

### PipeJson (in CvGame.cpp)
**Purpose**: JSON serialization utilities

| Function | Description |
|----------|-------------|
| `Escape(str)` | Escape string for JSON |
| `GetString(json, key)` | Extract string field |
| `GetInt(json, key, default)` | Extract integer field |

---

## Key Lua Popup Files

### Auto-Close Popups (Timer-based)
| File | Location | Popup Type |
|------|----------|------------|
| `NewEraPopup.lua` | `(1) Community Patch/LUA/` | New era notification |
| `NaturalWonderPopup.lua` | `(1) Community Patch/LUA/` | Natural wonder discovered |
| `TechAwardPopup.lua` | `(1) Community Patch/LUA/` | Free tech from great person |
| `LoadScreen.lua` | Multiple variants | Dawn of Man (game start) |

### Choice Popups (State-based + Pipe messaging)
| File | Location | Sends to Pipe |
|------|----------|---------------|
| `TechPopup.lua` | `(1) Community Patch/LUA/` | `popup_type: "choose_tech"` |
| `ProductionPopup.lua` | `(1) Community Patch/LUA/` | `popup_type: "choose_production"` |
| `ChoosePantheonPopup.lua` | `(1) Community Patch/LUA/` | `popup_type: "choose_pantheon"` |
| `ChooseReligionPopup.lua` | `(1) Community Patch/LUA/` | `popup_type: "choose_religion"` |
| `DeclareWarPopup.lua` | `(1) Community Patch/Core Files/Overrides/` | `popup_type: "city_captured"` |

---

## Python Orchestrator (`python/orchestrator/`)

### mcp_server.py
**Purpose**: MCP HTTP server exposing tools to LLM

| Method | Tool Name | Description |
|--------|-----------|-------------|
| `_get_game_state()` | `get_game_state` | Query game state by category |
| `_send_action()` | `send_action` | Send action command to DLL |
| `_end_turn()` | `end_turn` | End current turn |
| `_get_units()` | `get_units` | List all player units |
| `_get_log()` | `get_log` | Query message log history |
| `_add_note()` | `add_note` | Add note to game log |

### pipe_server.py
**Purpose**: Named pipe client connection to DLL

| Class/Method | Description |
|--------------|-------------|
| `PipeClient` | Async pipe connection manager |
| `StateProcessor` | Processes incoming DLL messages |
| `GameLogger` | JSONL message logging |

---

## State Categories (from `docs/state-schema.md`)

When using `get_game_state`, these categories are available:

| Category | Key Data |
|----------|----------|
| `game_level` | Turn number, era, game speed, map size |
| `cities` | All cities with population, production, buildings |
| `units` | All units with position, type, moves remaining |
| `technologies` | Research progress, available techs, queue |
| `policies` | Adopted policies, available branches |
| `diplomacy` | Relations, deals, wars with other civs |
| `resources` | Strategic/luxury resources, yields |
| `terrain` | Tile data, improvements, features |
| `victory` | Victory conditions progress |
| `religion` | Pantheon, founded religions, beliefs |

See `docs/state-schema.md` for complete field documentation.

---

## Documentation Notes

### Duplicate Documentation
`Community-Patch-DLL/docs/` contains copies of documentation that are also in `./docs/`:
- `protocol.md` - Same as `docs/protocol.md`
- `api.yaml` - Same as `docs/api.yaml`

**Use `./docs/` as the canonical source.** The copies in `Community-Patch-DLL/docs/` may become stale.

### Documentation Currency (as of session)
- **docs/protocol.md** - Current; covers session tracking, message types, architecture
- **docs/api.yaml** - Current; includes all popup hooks and commands
- **docs/state-schema.md** - Current; comprehensive 20-category reference
- **docs/logging.md** - Documents planned improvements, partially implemented
- **docs/unit-actions.md** - Current; covers move/found/sleep/skip actions

### Potentially Missing Documentation
- `PuppetCityPopup.lua` handling (may need docs/api.yaml update for puppet city choices)
