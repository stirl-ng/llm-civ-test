# System Inventory

Status ratings: `done` | `in-progress` | `needs-rework` | `scrap`

---

## C++ Pipe Layer
**Status: `done`**

Named pipe server, game event dispatch, command handling. Creates and owns `\\.\pipe\civv_llm`. All game-side logic for sending events and responding to commands lives here.

Files: `CvGameCoreDLL_Expansion2/GameStatePipe.cpp`, `CvGame.cpp`
Interfaces: Windows named pipe (out to orchestrator), `Game.SendPipeMessage()` (in from Lua), Civ V engine API

---

## Lua Popup Handlers
**Status: `in-progress`**

Auto-closes popups that would block `end_turn`. Choice popups also send available options to the pipe before closing. Each popup requires individual handling — there is no generic hook.

Files: `(1) Community Patch/LUA/` — individual popup Lua files
Interfaces: `Game.SendPipeMessage()` → C++ pipe layer
See: `docs/popups.md` for handling inventory

---

## Orchestrator
**Status: `done`**

Python bridge between the DLL pipe and the agent runner. Three components running together:
- `pipe_server.py`: Named pipe client, request/response routing via `request_id`
- `mcp_server.py`: Tool handler, 40+ game tools in `_TOOLS` dict
- `mcp_http_server.py`: HTTP wrapper at `localhost:8765`
- `game_state.py`: Thread-safe game metadata (turn, game_id, player_id)
- `message_logger.py`: Writes per-game JSONL logs to `python/logs/game_{game_id}.jsonl`

Interfaces: Named pipe (DLL), HTTP (agent runner), JSONL (dashboard, analysis)

---

## Tool Schemas
**Status: `needs-rework`**

OpenAI-format tool definitions sent to the LLM each turn. Manually kept in sync with `mcp_server._TOOLS`. Currently bifurcated: the orchestrator defines what it handles (`_TOOLS`), and `schemas.py` defines what the LLM sees. These were never auto-generated from each other — a consequence of the regex-to-native tool call migration. Easy to desync when adding tools.

Files: `python/agent_runtime/tools/schemas.py`
Interfaces: Consumed by model adapters; must mirror `mcp_server._TOOLS`

---

## Agent Turn Loop
**Status: `needs-rework`**

Currently polls orchestrator `/status` for new turns (violates push principle — see `docs/issues.md`). Target: subscribe to orchestrator SSE stream, receive `turn_start` events for this runner's `player_id`.

On turn start: build briefing (notifications + journal context + basic status) → send system prompt + briefing to LLM → execute tool calls → forced reflection before `end_turn` → loop until `end_turn` succeeds or timeout.

Journal tools (`record_lesson`, `get_recaps`, etc.) are handled locally here, not through the orchestrator. Each runner is scoped to one `player_id`; multiple runners can run simultaneously for multi-agent games.

Files: `python/experiments/run.py`
Interfaces: Orchestrator HTTP (→ SSE), model adapters, journal (local process)

Note: `interactive` mode (stdin prompting) is vestigial — keep `false` for unsupervised runs.

---

## Memory / Journal
**Status: `needs-rework`**

Persistent memory across turns and games. Current implementation has `TurnMemory` objects (structured, with mood/thoughts fields) that need to be replaced with a simpler model. Each model (`PlayerProfile`) has its own isolated memory.

**Target memory model (three things only):**
1. **Recaps** — LLM-written 2-4 sentence summary at end of each turn. Stored as `{turn, text}`. Last N injected into briefing automatically; full list queryable via `get_recaps()`. Kept forever.
2. **Strategy** — LLM's current stated goals for this game. Single string, updated by the LLM when its plan changes. Always injected into briefing.
3. **Lessons** — Cross-game generalizable principles. Written proactively by LLM during play. Top N injected into briefing; full list queryable. Reviewed/revised periodically (configurable cadence).

Files: `python/agent_runtime/memory/journal.py`, `python/agent_runtime/briefing.py`
Storage: `python/game_journal.json`
Interfaces: Briefing generator reads and injects; LLM calls tools to write (`record_lesson`, `record_recap`, `update_strategy`) and read (`get_recaps`, `get_lessons`)

---

## System Prompt + Personality
**Status: `needs-rework`**

LLM identity framing and behavior guidelines. `system_prompt.py` is monolithic — hard to iterate on individual sections. `personality.py` has personality archetypes used as game-start seeds. Goal is a modular composition system where prompt sections can be toggled/swapped for experimentation.

Files: `python/agent_runtime/prompts/system_prompt.py`, `python/agent_runtime/prompts/personality.py`
Interfaces: Prepended to every LLM call by the turn loop

---

## Model Adapters + Config
**Status: `in-progress`**

Model backends: OpenAI-compatible (`openai_adapter.py`), Gemini (`gemini_adapter.py`), Dummy (testing). All implement `ModelAdapter.generate(messages, tools) → GenerateResponse`. Config via YAML in `python/configs/experiments/` — specifies backend kind, model name, orchestrator URL, poll interval.

Files: `python/agent_runtime/models/`, `python/configs/experiments/`
Interfaces: `generate()` called by turn loop; API keys via environment variables

Open: Multi-model config design is ad-hoc. Model name normalization for journal scoping is implicit in `journal.py::set_current_player()` with no documented convention.

---

## Dashboard
**Status: `in-progress`**

Web debug UI showing message timeline, tool calls, LLM thoughts, game state. Reads per-game JSONL logs. Long-term goal: stream overlay showing what the AI is doing and thinking in real time.

Files: `python/orchestrator/dashboard.py`
Interfaces: Reads `python/logs/game_{game_id}.jsonl`; may query orchestrator HTTP
