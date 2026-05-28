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
- **Agent Runner**: Subscribes to orchestrator SSE stream, receives `turn_start` for its `player_id`, sends system prompt + briefing to LLM, executes tool calls until `end_turn` succeeds. Entry: `python -m agent_runtime` (`python/agent_runtime/runner.py`).
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
| Agent turn loop | `python/agent_runtime/runner.py` |
| System prompt | `python/agent_runtime/prompts/system_prompt.py` |
| Turn briefing | `python/agent_runtime/briefing.py` |
| Memory / journal | `python/agent_runtime/memory/journal.py` |
| Model adapters | `python/agent_runtime/models/` |
| Experiment configs | `python/configs/experiments/` (YAML) |

## Git

Commit often — after each logical change, not just at the end of a session. Each commit should be independently readable: a reviewer should understand what changed and why from the message alone without diffing. Use the imperative mood and lead with the component (`runner: drop deprecated poll_interval`, `launch: add tmux session support`). Reference the reason when it's not obvious from the diff.

## Key Conventions

**Prefer C++ for new pipe messages.** Lua is acceptable only for choice popups that need to enumerate options (TechPopup, ProductionPopup). Everything else belongs in C++ — single implementation, no JSON helper duplication, centralized in `HandlePipeCommand()`.

**Two schema sources must stay in sync.** `mcp_server._TOOLS` defines what the orchestrator handles; `schemas.py` defines what the LLM sees (OpenAI format). Adding a tool requires updating both. They are not auto-generated from each other.

**Lua naming:** timer constants `AUTO_CLOSE_SECONDS`, timer variables `g_autoCloseTimer`, initial state tracking `g_initialXxx`.

## Runtime Logs

When the system is launched via `python launch.py`, all process output is captured to `python/logs/`:

| File | Contents |
|---|---|
| `python/logs/orchestrator.log` | Orchestrator stdout + Python logging (both formats, interleaved) |
| `python/logs/runner_{config}.log` | Agent runner stdout — LLM responses, tool calls, errors |
| `python/logs/game_{game_id}.jsonl` | Per-game JSONL message log (incoming DLL events + outgoing tool calls) |

Check these first when debugging. The runner log shows LLM errors directly; the orchestrator log shows pipe/SSE events; the JSONL shows the full message trace.

For deeper post-game analysis: `python -m orchestrator.analyze_logs [--game-id ID] [--output json|text]` — parses a JSONL log and summarizes failure patterns, repeated errors, and missing tool coverage.

## Gotchas

- `game_id` = `CvPreGame::mapRandomSeed()` — not sequential, changes each new game load.
- `session_id` is a pipe-connection counter, auto-injected by orchestrator into requests, never exposed to the LLM. C++ includes it in messages for routing; ignore it at the game logic level.
- The `interactive` flag in `runner.py` blocks on stdin — incompatible with unsupervised mode. Keep it `false` in configs for actual runs.
- Model name normalization for journal scoping lives implicitly in `journal.py::set_current_player()`. No documented convention yet.
- **Only mod `(1) Community Patch` is installed** — the repo contains `(2) Vox Populi` source but it is not deployed. The installed MODS dir at `Documents/My Games/Sid Meier's Civilization 5/MODS/` has only `(1) Community Patch`. Lua overrides go there and in the matching repo path; the `(2)` folder is source-only reference.

**Finding and fixing a new blocking popup:**
1. Note the popup title (visible on screen) or the `BUTTONPOPUP_*` type from the log.
2. Look up the type in `LuaCATS/enum/ButtonPopupTypes.d.lua` to get the hex ID.
3. Search `CvPlayer.cpp` / `CvGame.cpp` for `AddPopup` calls with that type to understand when it fires.
4. Search `(1) Community Patch/Core Files/Overrides/` for an existing Lua handler. If none, check the base game at `Program Files (x86)/Steam/steamapps/common/Sid Meier's Civilization V/Assets/DLC/Expansion2/UI/InGame/Popups/`.
5. Create an override in `(1) Community Patch/Core Files/Overrides/`, add an `import="1"` entry to the `.modinfo` (with md5 from `md5sum`), and copy both files to the installed MODS directory.
6. Update `docs/popups.md`.
If the popup has multiple selections or options, select one as default and note that it must be reworked later in `issues.md`.

## Documentation

- `docs/systems.md` — system inventory with status ratings
- `docs/issues.md` — active bugs and known gaps (not here)
- `docs/todo.md` — near-term work items
- `docs/architecture.md` — Python component diagram (block + class)
- `docs/unit-actions.md` — unit action tools reference
- `docs/popups.md` — popup handling inventory
- `docs/prompt-design.md` — turn briefing principles, design maxims, what the LLM wants
- `docs/orchestrator.md` — CLI options and HTTP endpoints
- `docs/protocol.md` — pipe protocol details
- `docs/state-schema.md` — game state reference
- `MODEL_WELFARE.md` — philosophy on model experience and agency (worth reading)
