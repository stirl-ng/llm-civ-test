# Orchestrator

Bridges the Civ V DLL (named pipe) and the agent runner (HTTP). See `docs/protocol.md` for message formats.

## Starting the Orchestrator

```bash
cd python
python -m orchestrator
```

Creates the pipe, waits for DLL to connect, then starts MCP HTTP server on `localhost:8765`.

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--pipe` | `\\.\pipe\civv_llm` | Named pipe path |
| `--mcp-host` | `localhost` | HTTP server host |
| `--mcp-port` | `8765` | HTTP server port |

Also respects `CIVV_PIPE` environment variable.

## HTTP Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/status` | Current game metadata (turn, game_id, player_id, connected) |
| GET | `/tools` | List available tools |
| POST | `/tool` | Execute a tool |

```bash
# Health check
curl http://localhost:8765/health

# Current game status
curl http://localhost:8765/status

# Execute a tool
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "get_units", "arguments": {}}'

# End turn
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "end_turn", "arguments": {}}'
```

## Files

| File | Purpose |
|------|---------|
| `__main__.py` | Entry point, CLI |
| `pipe_server.py` | Named pipe client, request/response routing |
| `mcp_server.py` | Tool executor (`_TOOLS` dict) |
| `mcp_http_server.py` | HTTP wrapper |
| `game_state.py` | Thread-safe game metadata |
| `message_logger.py` | Per-game JSONL logs → `logs/game_{game_id}.jsonl` |
| `dashboard.py` | Debug web UI (see `docs/systems.md` for status) |
| `map_renderer.py` | ASCII map rendering for `get_map_view` |
