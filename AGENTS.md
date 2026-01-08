# Repository Guidelines

## Project Structure & Module Organization
- `Community-Patch-DLL/`: Civ V Community Patch DLL (submodule) with LLM protocol implementation.
  - `CvGameCoreDLL_Expansion2/GameStatePipe.cpp/.h`: Threaded named pipe communication.
  - `CvGameCoreDLL_Expansion2/CvGame.cpp`: Command handlers and hook functions.
  - `protocol.yaml`: Authoritative protocol specification (gitignored, local only).
- `python/`: Orchestrator that bridges DLL and LLMs via HTTP.
  - `orchestrator/`: Main package.
    - `pipe_server.py`: Named pipe client connecting to DLL.
    - `mcp_server.py`: MCP protocol implementation.
    - `mcp_http_server.py`: HTTP server for MCP.
    - `dashboard.py`: Web UI for monitoring.
  - `examples/`: Example client scripts.
- `docs/`: Documentation.
  - `protocol.md`: DLL ↔ Orchestrator message protocol.
  - `orchestrator.md`: Orchestrator CLI and architecture.
  - `getting-started.md`: Quick start guide for MCP server.
  - `state-schema.md`: Game state schema reference.
- Root: `README.md`, `AGENTS.md`.

## Build, Test, and Development Commands
- DLL build: See `Community-Patch-DLL/DEVELOPMENT.md`.
- Python env: `py -3.11 -m venv .venv && .\.venv\Scripts\Activate.ps1 && pip install -r python/requirements.txt`.
- Run orchestrator: From `python/`, `python -m orchestrator` (creates pipe `\\.\pipe\civv_llm`, starts MCP server on port 8765).
- Run with dashboard: `python -m orchestrator --dashboard` (adds web UI on port 5000).
- Debug mode: `python -m orchestrator --debug` (displays DLL messages without LLM processing).
- Tests (Python): `pytest -q` in `python/`.
- Format (Python): `black .` or `ruff format`.

## Coding Style & Naming Conventions
- C++: C++14, 4-space indent, PascalCase types, camelCase methods/vars, UPPER_CASE constants. Prefer RAII; avoid raw new/delete.
- Python: PEP 8, 4-space indent, snake_case, type hints; docstrings for public APIs.
- JSON: snake_case keys (e.g., `turn`, `city_id`, `unit_id`), minimal payloads.

## Architecture Overview

```
┌──────────────┐         ┌──────────────┐         ┌─────────────┐
│  Civ V DLL   │ ◄─────► │ Orchestrator │ ◄─────► │     LLM     │
│   (Game)     │  Pipe   │  (Python)    │  HTTP   │             │
└──────────────┘         └──────────────┘         └─────────────┘
```

**DLL pipe architecture:**
- Background thread owns pipe connection and reads continuously
- Commands queued in thread-safe queue, processed on main thread
- Window subclassing wakes main thread when commands arrive
- Responses sent directly on main thread

**Sequential turn flow:**
1. DLL sends `turn_start` with game state via named pipe
2. Orchestrator updates state and exposes via MCP HTTP server
3. LLM queries state (`get_units`, `get_cities`, etc.) and sends actions
4. Each action is forwarded to DLL immediately, response returned to LLM
5. DLL forwards game events via hooks (notifications, popups, diplomacy, tech)
6. LLM calls `end_turn` with required `turn` parameter when done
7. Orchestrator forwards `end_turn` to DLL, which advances turn

**DLL hooks** (forward game events to pipe):
- `SendNotificationToPipe`: Player notifications
- `SendPopupToPipe`/`AddPopupWithPipe`: UI popups
- `SendDiplomaticMessageToPipe`: Diplomacy with deal details
- `SendTechResearchedToPipe`: Technology completion

See `docs/protocol.md` for message formats.

## Testing Guidelines
- Python: `pytest` with good coverage. Unit tests in `python/tests/`.
- In-game: For DLL changes, test with orchestrator in debug mode to verify message formats.

## Commit & Pull Request Guidelines
- Commits: Use Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`).
- PRs: Include purpose, validation steps, and before/after notes. Keep PRs focused.

## Security & Configuration Tips
- Pipe name: Default `\\.\pipe\civv_llm`; override with `--pipe` flag or `CIVV_PIPE` env var.
- Validation: Sanitize inbound JSON; DLL validates action legality.
- DLL concurrency: Pipe I/O runs in background thread; commands processed on main game thread.
- Python concurrency: Pipe I/O runs in background thread; main thread handles HTTP/MCP.
