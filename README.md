# Civ V LLM Bridge

Enable large language models (LLMs) to play **Civilization V** through a custom DLL and Python orchestrator.

The DLL exports game state and accepts actions via a named pipe. The orchestrator exposes this as an HTTP API that LLMs can call to query state, send commands, and play the game.

## Architecture

```
┌──────────────┐         ┌──────────────┐         ┌─────────────┐
│  Civ V DLL   │ ◄─────► │ Orchestrator │ ◄─────► │     LLM     │
│   (Game)     │  Pipe   │  (Python)    │  HTTP   │             │
└──────────────┘         └──────────────┘         └─────────────┘
```

**Turn flow:**
1. DLL sends `turn_start` with game state via named pipe
2. Orchestrator caches state and exposes via HTTP (MCP server)
3. LLM queries state and sends actions one at a time
4. Each action is forwarded to DLL, response returned to LLM
5. LLM calls `end_turn` when done
6. DLL advances to next turn

## Features

- **Game state export**: Cities, units, tech, tiles, diplomacy, resources
- **Action execution**: Research, policies, production, unit movement, combat
- **Sequential flow**: LLM sees result of each action before deciding the next
- **HTTP API**: Query tools and action tools via simple POST requests
- **Monitoring dashboard**: Web UI with log viewer and manual command buttons
- **Named pipe IPC**: Fast, reliable communication with the game

## Quick Start

### 1. Install the DLL

The `Community-Patch-DLL` submodule contains the Civ V DLL with LLM protocol support.

```bash
git submodule update --init
```

Build the DLL (requires Visual Studio):
```bash
# See Community-Patch-DLL/DEVELOPMENT.md for build instructions
```

Install the built DLL as a Civ V mod.

### 2. Run the Orchestrator

```bash
cd python
pip install -r requirements.txt
python -m orchestrator
```

This creates the named pipe and starts the MCP HTTP server on `http://localhost:8765`.

**With monitoring dashboard:**
```bash
python -m orchestrator --dashboard
```

Opens a web dashboard at `http://localhost:5000`.

### 3. Start a Game

1. Launch Civ V with the LLM-enabled DLL mod active
2. Start a hotseat game with an LLM-controlled player
3. When it's the LLM player's turn, the DLL connects to the orchestrator

### 4. Connect an LLM

The LLM can now query state and send actions via HTTP:

```bash
# Get game state
curl http://localhost:8765/state

# Send an action
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "send_action", "arguments": {"action": {"kind": "research", "tech": "TECH_POTTERY"}}}'

# End turn
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "end_turn", "arguments": {}}'
```

## Available Tools

| Tool | Description |
|------|-------------|
| `get_game_state` | Get current game state (cities, units, tech, etc.) |
| `get_cities` | Get detailed city information |
| `get_units` | Get unit information |
| `get_tech_tree` | Get technology status |
| `get_diplomacy` | Get diplomatic relations |
| `get_resources` | Get strategic and luxury resources |
| `get_available_choices` | Get pending decisions |
| `send_action` | Send an action to the game |
| `end_turn` | Signal done with turn |

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `--pipe` | `\\.\pipe\civv_llm` | Named pipe path |
| `--mcp-port` | `8765` | HTTP server port |
| `--turn-timeout` | `300` | Max seconds per turn |
| `--dashboard` | off | Enable web dashboard |

## Documentation

- [Getting Started](docs/getting-started.md) - Detailed setup guide
- [Orchestrator](docs/orchestrator.md) - CLI options and architecture
- [Protocol](docs/protocol.md) - DLL ↔ Orchestrator message format
- [State Schema](docs/state-schema.md) - Game state structure

## Project Structure

```
├── Community-Patch-DLL/   # Civ V DLL with LLM protocol (submodule)
├── python/
│   ├── orchestrator/      # Main package
│   │   ├── __main__.py    # Entry point
│   │   ├── pipe_server.py # Named pipe server
│   │   ├── mcp_server.py  # Tool executor
│   │   ├── mcp_http_server.py # HTTP server
│   │   └── dashboard.py   # Web monitoring UI
│   └── requirements.txt
├── docs/                  # Documentation
└── README.md
```

## Development

```bash
# Debug mode - view DLL messages without LLM
python -m orchestrator --debug

# Run tests
cd python && pytest

# Format code
black .
```

## License

Part of the llm-civ-test project.
