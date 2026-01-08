# Getting Started with Civ V MCP Server

This guide will help you set up and use the MCP (Model Context Protocol) server for Civilization V, enabling LLMs to control and query the game.

## What is the MCP Server?

The MCP server exposes the Civilization V game state and control interface through an HTTP API that LLMs can use. This allows AI assistants like Claude to:

- **Query game information**: Cities, units, technology, diplomacy, resources, etc.
- **Command the game**: Research technologies, adopt policies, move units, manage cities
- **Make strategic decisions**: Analyze victory conditions, plan expansion, coordinate military

## Quick Start

### Start the Orchestrator

```bash
cd python
python -m orchestrator
```

This will:
1. Create the named pipe and wait for the Civ V DLL to connect
2. Start the MCP HTTP server on `http://localhost:8765`

**With monitoring dashboard:**
```bash
python -m orchestrator --dashboard
```

The dashboard provides a web UI at `http://localhost:5000` with:
- Real-time log viewer with filtering
- Buttons to manually trigger MCP commands

### Configuration Options

```bash
# Custom MCP server port
python -m orchestrator --mcp-port 9000

# Custom turn timeout (deprecated - no longer used)
python -m orchestrator --turn-timeout 120

# Debug mode (view DLL messages without processing)
python -m orchestrator --debug
```

## Using the MCP Server

### From HTTP API

**Get health status:**
```bash
curl http://localhost:8765/health
```

**Get current state:**
```bash
curl http://localhost:8765/state
```

**List available tools:**
```bash
curl http://localhost:8765/tools
```

**Call a tool:**
```bash
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "get_game_state",
    "arguments": {"category": "game_level", "format": "json"}
  }'
```

**Send an action:**
```bash
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "send_action",
    "arguments": {
      "action": {"kind": "research", "tech": "TECH_POTTERY"}
    }
  }'
```

**End turn (turn parameter is required):**
```bash
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "end_turn",
    "arguments": {"turn": 7, "notes": "Finished turn decisions"}
  }'
```

## Available Tools

See docs/protocol.md


## Sequential Action Flow

The MCP server uses a **sequential action flow**:

1. LLM calls `send_action` with an action
2. Action is sent immediately to the DLL
3. DLL executes the action and returns a response
4. Response is returned to the LLM
5. LLM can see the result before deciding the next action
6. Repeat until LLM calls `end_turn`

This allows the LLM to react to the results of each action, making more intelligent decisions.


## Architecture

```
┌──────────────┐         ┌──────────────┐         ┌─────────────┐
│  Civ V DLL   │ ◄─────► │ Orchestrator │ ◄─────► │  LLM/Client │
│   (Game)     │  Pipe   │  (Python)    │  HTTP   │             │
└──────────────┘         └──────────────┘         └─────────────┘
        │                        │
        │                   MCP Server
        │                   (port 8765)
        │                        │
        │                   Dashboard
        │                   (port 5000)
```

**Sequential Flow:**
1. DLL sends `turn_start` with game state via named pipe
2. Orchestrator updates state and exposes pipe connection
3. LLM queries state via HTTP (forwarded to DLL)
4. LLM sends action via HTTP
5. Orchestrator forwards action to DLL immediately
6. DLL executes action and returns result
7. Result returned to LLM
8. LLM can send more actions or call `end_turn` with required `turn` parameter
9. Orchestrator forwards `end_turn` to DLL
10. DLL advances to next turn

## Troubleshooting

### Server won't start

**Error: `Address already in use`**
- Another process is using port 8765
- Solution: Set a different port with `--mcp-port 9000`

### No game state available

- The orchestrator is waiting for the Civ V DLL to connect
- Make sure the game is running with the LLM-enabled DLL
- Check that the pipe name matches (default: `\\.\pipe\civv_llm`)

### Actions returning errors

- Check the action format matches what the DLL expects
- See [protocol.md](protocol.md) for message formats
- Check the DLL logs for more details

### Connection refused

- Make sure the orchestrator is running
- Check that you're using the correct host/port

## Next Steps

- Read [orchestrator.md](orchestrator.md) for detailed CLI options
- Read [protocol.md](protocol.md) for the protocol specification
- Check [state-schema.md](state-schema.md) for understanding available game data

## Development

### Running in Debug Mode

View game state messages without LLM processing:

```bash
python -m orchestrator --debug

# Show raw JSON
python -m orchestrator --debug --raw
```

### Testing the Dashboard

Run just the dashboard for UI testing:

```bash
python -m orchestrator --dashboard-only
```

Note: MCP commands will fail without the full orchestrator running.
