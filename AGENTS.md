# Repository Guidelines

## Project Structure & Module Organization
- `Community-Patch-DLL/`: Civ V Community Patch DLL (submodule) with LLM protocol implementation.
- `python/`: Orchestrator that bridges DLL and LLMs via HTTP.
  - `orchestrator/`: Main package - pipe server, MCP server, dashboard.
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

**Sequential turn flow:**
1. DLL sends `turn_start` with game state via named pipe
2. Orchestrator caches state and exposes via MCP HTTP server
3. LLM queries state and sends actions one at a time
4. Each action is forwarded to DLL immediately, response returned to LLM
5. LLM calls `end_turn` when done
6. Orchestrator signals DLL to advance turn

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
- Concurrency: Pipe I/O runs in background thread; main thread handles HTTP.
