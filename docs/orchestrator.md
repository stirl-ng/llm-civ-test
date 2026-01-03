# Orchestrator

The orchestrator bridges the Civ V DLL and external LLMs. It manages turn flow, caches game state, and exposes tools via HTTP for LLM decision-making.

See [protocol.md](protocol.md) for the full protocol specification.

## Architecture

```
DLL ◄──Named Pipe──► Orchestrator ◄──HTTP──► LLM
                          │
                     MCP HTTP Server
                     localhost:8765
```

## Quick Start

```bash
# Run orchestrator (creates pipe, waits for DLL, starts MCP server)
cd python
python -m orchestrator

# With options
python -m orchestrator --mcp-port 9000 --turn-timeout 120

# With monitoring dashboard
python -m orchestrator --dashboard

# Debug mode (just display DLL messages, no LLM)
python -m orchestrator --debug
```

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--pipe` | `\\.\pipe\civv_llm` | Named pipe path |
| `--once` | - | Process one turn then exit |
| `--mcp-host` | `localhost` | MCP HTTP server host |
| `--mcp-port` | `8765` | MCP HTTP server port |
| `--turn-timeout` | `300` | Max seconds per turn |
| `--dashboard` | - | Start the monitoring dashboard |
| `--dashboard-host` | `0.0.0.0` | Dashboard host |
| `--dashboard-port` | `5000` | Dashboard port |
| `--dashboard-only` | - | Run only the dashboard (for UI testing) |
| `--debug` | - | Debug mode: display messages only |
| `--raw` | - | In debug mode, show raw JSON |

## Turn Flow

1. **DLL sends `turn_start`** with full game state
2. **Orchestrator caches state** and opens turn for LLM
3. **LLM makes HTTP tool calls** to `/tool` endpoint:
   - Query tools read from cache (fast)
   - Action tools forward to DLL immediately, wait for result
4. **LLM calls `end_turn`** when done deciding
5. **Orchestrator sends `end_turn`** to DLL
6. **DLL advances** to next player

## MCP HTTP Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/state` | Current cached game state |
| GET | `/tools` | List available tools |
| POST | `/tool` | Execute a tool |

### Tool Call Example

```bash
# Query state
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "get_units", "arguments": {}}'

# Send action (sent immediately to DLL, response returned)
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "send_action", "arguments": {"action": {"kind": "move_unit", "unit_id": 5, "to": [10, 12]}}}'

# End turn
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "end_turn", "arguments": {"notes": "Moved warrior, started granary"}}'
```

## Available Tools

### Query Tools (Read from Cache)

| Tool | Description |
|------|-------------|
| `get_game_state` | Full or filtered game state |
| `get_cities` | City information |
| `get_units` | Unit information |
| `get_tech_tree` | Technology status |
| `get_diplomacy` | Diplomatic relations |
| `get_resources` | Resources owned |
| `get_victory_progress` | Victory condition status |
| `get_available_choices` | Pending decisions |
| `format_state` | Human-readable summary |

### Action Tools (Forward to DLL)

| Tool | Description |
|------|-------------|
| `send_action` | Execute a game action immediately, returns DLL response |

### Turn Control

| Tool | Description |
|------|-------------|
| `end_turn` | Signal done, complete turn |

## Timeouts

- **Turn timeout**: LLM has N seconds to complete their turn (default 300s)
- If timeout occurs, turn ends automatically

## Files

| File | Purpose |
|------|---------|
| `orchestrator/__main__.py` | Entry point, CLI, turn loop |
| `orchestrator/mcp_server.py` | Tool executor, turn state |
| `orchestrator/mcp_http_server.py` | HTTP server wrapper |
| `orchestrator/pipe_server.py` | Named pipe server, PipeConnection |
| `orchestrator/dashboard.py` | Flask monitoring dashboard |
| `orchestrator/formatting.py` | State formatting utilities |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CIVV_PIPE` | Override default pipe path |
