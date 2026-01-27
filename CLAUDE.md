# Claude Code Conventions for LLM-Civ Integration

This document establishes patterns and conventions for the LLM pipe integration in this Civ V mod.

## Design Philosophy: LLM as a Player, Not a Popup Responder

**Key Principle**: The LLM should have access to the same information as a human player, at the same time, through MCP query tools - NOT by waiting for popup events.

### What this means:
- **Humans** can look at their cities anytime and see what's available to build
- **LLM** should be able to call `get_city_production` anytime to see the same info
- **Humans** can open the tech tree and see what's researchable
- **LLM** should be able to call `get_available_techs` anytime

### Popups are UI conveniences, not data sources:
- Popups prompt humans to make decisions, but humans don't NEED them
- The LLM should proactively query state and take actions, not wait for `popup_choice_needed` events
- Popup hooks are fallbacks, not the primary flow

### Implementation pattern:
1. **Query tools** (`get_city_production`, `get_available_techs`) - LLM asks for info when needed
2. **Action tools** (`set_city_production`, `choose_tech`) - LLM takes action directly
3. **Popup events** - Optional notifications, auto-closed by Lua, LLM doesn't depend on them

This mimics how a skilled human plays: they already know what they want to build before the popup appears.

## Design Philosophy: Purposeful Movement, Not Random Wandering

**Key Principle**: Units should move to SPECIFIC tiles for CLEAR reasons, not move randomly or "just because."

### The Problem: Random Movement
A common issue with LLM gameplay is units moving without purpose:
- Scouts retreading already-explored ground
- Workers moving randomly instead of to tiles they'll improve
- Military units wandering aimlessly
- Units moving "just to do something" each turn

### What this means:
- **Humans** look at the map, identify objectives, then move units toward those objectives
- **LLM** should query map state first (`get_map_view`, `get_reachable_tiles`), identify objectives, THEN move
- **Humans** use multi-turn auto-pathing - click a distant tile and let the unit follow the path
- **LLM** should do the same - `move_unit` to distant tiles, trust the game's pathfinding

### Movement Best Practices:

**GOOD - Specific destination with clear purpose:**
```
move_unit(unit_id=5, to=[23, 18])  // Move worker to wheat tile to build farm
move_unit(unit_id=8, to=[40, 25])  // Move scout to unexplored region
```

**BAD - Vague or random movement:**
```
move_unit(unit_id=5, to=[11, 13])  // Move worker "northeast" - why?
move_unit(unit_id=8, to=[12, 12])  // Move scout one tile - retreading ground
```

### Multi-Turn Auto-Pathing
The `move_unit` command supports multi-turn movement:
- Game calculates full A* path to destination
- Path is cached and auto-continues on subsequent turns
- LLM doesn't need to re-issue commands every turn
- Unit automatically follows path until destination reached

**Don't micro-manage!** If a unit is already moving toward an objective (activity="MISSION"), let it complete the journey unless circumstances change.

## Known Issues (TODO)

### 1. Unhandled popups block end_turn
These popups block `end_turn` but aren't reported via pipe:
- Meet civilization dialog
- Goody hut rewards
- Natural wonder discovered
- Policy screen (when open in UI)

Need to add auto-close handlers in Lua for these.

### 2. NO_ENDTURN_BLOCKING_TYPE gives no info
When `blocking_type_id` is -1, we get no diagnostic info about what's blocking.

## Architecture Overview

The LLM integration uses a named pipe (`\\.\pipe\civv_llm`) for bidirectional communication:
- **C++ (DLL)**: Handles pipe connection, sends game events, processes commands
- **Lua (UI)**: Auto-closes popups, sends choice options to pipe
- **Python (Orchestrator)**: MCP server that bridges the game to LLM tools

## Tools

**The code is the documentation.** Call `get_tools` to see all available tools with descriptions.

Source of truth: `python/orchestrator/mcp_server.py` - the `_TOOLS` dict defines all implemented tools, and handler docstrings provide descriptions.

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
Examples: NewEraPopup, NaturalWonderPopup, TechAwardPopup, LoadScreen

**Pattern**: Timer-based auto-close in Lua, any info sent from C++

```lua
local g_autoCloseTimer = 0
local AUTO_CLOSE_SECONDS = 2.0

ContextPtr:SetUpdate(function(fDTime)
    if not ContextPtr:IsHidden() then
        g_autoCloseTimer = g_autoCloseTimer + fDTime
        if g_autoCloseTimer >= AUTO_CLOSE_SECONDS then
            g_autoCloseTimer = 0
            OnClose()
        end
    end
end)
```

### 2. Choice Popups (Requires Selection)
Examples: TechPopup, ProductionPopup, ChooseReligionPopup, ChoosePantheonPopup

**Pattern**: State-based auto-close in Lua, sends options via pipe

```lua
local g_initialState = nil

-- On popup open
g_initialState = GetCurrentState()
SendChoicesToPipe()

-- In SetUpdate handler - close when state changes
ContextPtr:SetUpdate(function(fDTime)
    if not ContextPtr:IsHidden() then
        if GetCurrentState() ~= g_initialState then
            ClosePopup()
        end
    end
end)
```

## Adding New Pipe Commands

### C++ Side (CvGame.cpp)

Sending messages:
```cpp
void CvGame::SendXxxToPipe()
{
    if (!m_kGameStatePipe.IsRunning())
        return;

    std::ostringstream payload;
    payload << "{\"type\":\"xxx\"";
    payload << ",\"game_id\":" << CvPreGame::mapRandomSeed();
    payload << ",\"session_id\":" << m_kGameStatePipe.GetSessionId();
    payload << "}";

    m_kGameStatePipe.SendMessage(payload.str());
}
```

Handling commands in `HandlePipeCommand()`:
```cpp
else if (msgType == "your_command")
{
    // Parse with PipeJson::GetInt(), PipeJson::GetString()
    // Execute game action
    // Send response via SendRawMessageToPipe()
}
```

### Python Side (mcp_server.py)

Add to `_TOOLS` dict and implement handler:
```python
_TOOLS = {
    "your_tool": ("_your_tool", {"param": "required int"}),
}

def _your_tool(self, args: dict) -> dict:
    """One-line description shown to LLM."""
    param = self._require_param(args, "param", int)
    return self._send_pipe_request("your_command", param=param)
```

## File Locations

- **C++ Pipe Logic**: `CvGameCoreDLL_Expansion2/GameStatePipe.cpp`, `CvGame.cpp`
- **Lua Popups**: `(1) Community Patch/LUA/`
- **MCP Server**: `python/orchestrator/mcp_server.py`

## Naming Conventions

- Timer constants: `AUTO_CLOSE_SECONDS`
- Timer variables: `g_autoCloseTimer`
- Initial state tracking: `g_initialXxx`

## Documentation

- `docs/getting-started.md` - Setup and quickstart
- `docs/orchestrator.md` - CLI options and HTTP endpoints
- `docs/protocol.md` - Pipe protocol architecture
- `docs/state-schema.md` - Game state reference
- `docs/unit-actions.md` - Unit action examples
- `docs/llm-agent-design.md` - Agent architecture philosophy
