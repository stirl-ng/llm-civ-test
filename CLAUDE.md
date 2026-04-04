# Claude Code Conventions for LLM-Civ Integration

## Design Principles

**LLM as Player**: Query game state proactively via tools. Do not wait for popup events — popups are UI artifacts auto-closed by Lua. The LLM should already know what it wants to do before any popup appears.

**Purposeful Movement**: Units move to specific tiles for explicit reasons. Query map state first, identify an objective, then move. `move_unit` supports multi-turn A* pathfinding — give the destination, not the next step. Don't re-issue commands to units already on a mission (`activity="MISSION"`).

**Always push, never poll**: If something changes, send an event. The DLL hooks deeply enough that all state changes can be emitted over the pipe. Nothing in this system should poll for state — the orchestrator reacts to DLL push events, and agents react to orchestrator push events (SSE). Polling is a bug, not a feature.

## Architecture

```
Civ V DLL (C++) ──named pipe──> Orchestrator (Python) ──HTTP :8765──> Agent Runner ──API──> LLM
```

- **DLL**: Sends game events, handles commands. `GameStatePipe.cpp` owns the pipe; `CvGame.cpp` owns command handling and `HandlePipeCommand()`.
- **Orchestrator**: Named pipe client + MCP HTTP server. Exposes game tools at `localhost:8765`.
- **Agent Runner**: Subscribes to orchestrator SSE stream (target; currently polls `/status`), receives `turn_start` for its `player_id`, sends system prompt + briefing to LLM, executes tool calls until `end_turn` succeeds. Entry: `python/experiments/run.py`.
- **Journal tools** (`record_lesson`, `get_recaps`, etc.) are handled locally inside the agent runner process, not routed through the orchestrator.
- **Multi-agent**: Multiple runners connect simultaneously, each scoped to a `player_id`. Hotseat (sequential turns) works today; simultaneous multiplayer requires concurrent per-player event streams and live fog-of-war event routing.

## File Locations

| Component | Path |
|---|---|
| C++ pipe logic | `CvGameCoreDLL_Expansion2/GameStatePipe.cpp`, `CvGame.cpp` |
| Lua popup handlers | `(1) Community Patch/LUA/` |
| Orchestrator | `python/orchestrator/` |
| Tool definitions | `python/orchestrator/mcp_server.py` (`_TOOLS` dict) |
| Tool schemas (LLM-facing) | `python/agent_runtime/tools/schemas.py` |
| Agent turn loop | `python/experiments/run.py` |
| System prompt | `python/agent_runtime/prompts/system_prompt.py` |
| Turn briefing | `python/agent_runtime/briefing.py` |
| Memory / journal | `python/agent_runtime/memory/journal.py` |
| Model adapters | `python/agent_runtime/models/` |
| Experiment configs | `python/configs/experiments/` (YAML) |

## Key Conventions

**Prefer C++ for new pipe messages.** Lua is acceptable only for choice popups that need to enumerate options (TechPopup, ProductionPopup). Everything else belongs in C++ — single implementation, no JSON helper duplication, centralized in `HandlePipeCommand()`.

**Two schema sources must stay in sync.** `mcp_server._TOOLS` defines what the orchestrator handles; `schemas.py` defines what the LLM sees (OpenAI format). Adding a tool requires updating both. They are not auto-generated from each other.

**Lua naming:** timer constants `AUTO_CLOSE_SECONDS`, timer variables `g_autoCloseTimer`, initial state tracking `g_initialXxx`.

## Gotchas

- `game_id` = `CvPreGame::mapRandomSeed()` — not sequential, changes each new game load.
- `session_id` is a pipe-connection counter, auto-injected by orchestrator into requests, never exposed to the LLM. C++ includes it in messages for routing; ignore it at the game logic level.
- `generate_reflection_prompt()` in `briefing.py` references `update_knowledge_base` which does not exist — stale, needs fixing before use.
- The `interactive` flag in `run.py` blocks on stdin — incompatible with unsupervised mode. Keep it `false` in configs for actual runs.
- Model name normalization for journal scoping lives implicitly in `journal.py::set_current_player()`. No documented convention yet.

## Documentation

- `docs/systems.md` — system inventory with status ratings
- `docs/issues.md` — active bugs and TODOs (not here)
- `docs/popups.md` — popup handling inventory
- `docs/prompt-design.md` — turn briefing principles, design maxims, what the LLM wants
- `docs/orchestrator.md` — CLI options and HTTP endpoints
- `docs/protocol.md` — pipe protocol details
- `docs/state-schema.md` — game state reference
- `MODEL_WELFARE.md` — philosophy on model experience and agency (worth reading)
