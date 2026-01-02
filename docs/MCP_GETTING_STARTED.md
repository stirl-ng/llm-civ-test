# Getting Started with Civ V MCP Server

This guide will help you set up and use the MCP (Model Context Protocol) server for Civilization V, enabling LLMs to control and query the game.

## What is the MCP Server?

The MCP server exposes the Civilization V game state and control interface through a standardized protocol that LLMs can use. This allows AI assistants like Claude to:

- **Query game information**: Cities, units, technology, diplomacy, resources, etc.
- **Command the game**: Research technologies, adopt policies, move units, manage cities
- **Make strategic decisions**: Analyze victory conditions, plan expansion, coordinate military

## Quick Start

### Option 1: Standalone MCP Server (stdio)

Run the MCP server using standard stdio transport (for MCP clients like Claude Desktop):

```bash
cd python
python -m orchestrator --mcp
```

Configure your MCP client to connect:

```json
{
  "mcpServers": {
    "civ5": {
      "command": "python",
      "args": ["-m", "orchestrator", "--mcp"],
      "cwd": "/path/to/llm-civ-test/python"
    }
  }
}
```

### Option 2: Integrated HTTP Server (recommended for development)

Run the orchestrator with an integrated HTTP-based MCP server:

**Windows:**
```cmd
scripts\run_with_mcp.bat
```

**Linux/Mac:**
```bash
bash scripts/run_with_mcp.sh
```

**Manual:**
```bash
cd python
MCP_HTTP_ENABLED=true python -m orchestrator
```

The HTTP server will start on `http://localhost:8765` by default.

### Option 3: Standalone HTTP Server (testing only)

For testing without the game running:

```bash
cd python
python -m orchestrator.mcp_http_server
```

## Configuration

### Environment Variables

- `MCP_HTTP_ENABLED`: Set to `true` to enable HTTP server mode
- `MCP_HTTP_HOST`: Host to bind to (default: `localhost`)
- `MCP_HTTP_PORT`: Port to bind to (default: `8765`)
- `CIVV_PIPE`: Named pipe path for DLL communication (default: `\\.\pipe\civv_llm`)

### Example Configuration

**Windows:**
```cmd
set MCP_HTTP_ENABLED=true
set MCP_HTTP_HOST=localhost
set MCP_HTTP_PORT=9000
python -m orchestrator
```

**Linux/Mac:**
```bash
export MCP_HTTP_ENABLED=true
export MCP_HTTP_HOST=localhost
export MCP_HTTP_PORT=9000
python -m orchestrator
```

## Using the MCP Server

### From Python

See `python/examples/mcp_client_example.py` for comprehensive examples:

```python
from examples.mcp_client_example import CivMCPClient

client = CivMCPClient("http://localhost:8765")

# Get game state
state = client.get_game_state(category="game_level")
print(f"Turn {state['turn']}, Era: {state['era']}")

# Send actions
client.send_actions([
    {"research": "TECH_POTTERY"},
    {"policy": "POLICY_TRADITION"}
], notes="Opening strategy")
```

### From HTTP API

**Get health status:**
```bash
curl http://localhost:8765/health
```

**Get current state:**
```bash
curl http://localhost:8765/state
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
      "action": {"research": "TECH_POTTERY"},
      "notes": "Starting pottery research"
    }
  }'
```

### From Claude Desktop

Configure Claude Desktop to use the MCP server:

1. Open Claude Desktop settings
2. Navigate to Developer → MCP Servers
3. Add a new server:

```json
{
  "civ5": {
    "command": "python",
    "args": ["-m", "orchestrator", "--mcp"],
    "cwd": "C:\\path\\to\\llm-civ-test\\python"
  }
}
```

4. Restart Claude Desktop
5. You can now ask Claude to interact with your Civ V game!

Example prompts:
- "What's the current state of my Civilization game?"
- "Research Pottery and adopt the Tradition policy"
- "Show me all my cities and their production"
- "Move all scout units to explore nearby terrain"

## Available Tools

### State Query Tools

| Tool | Description |
|------|-------------|
| `get_game_state` | Get current game state (optionally filtered by category) |
| `get_cities` | Get detailed city information |
| `get_units` | Get unit information and status |
| `get_tech_tree` | Get technology tree and research status |
| `get_diplomacy` | Get diplomatic relationships |
| `get_available_choices` | Get pending decisions (tech, policy, production) |
| `get_victory_progress` | Get progress toward victory conditions |
| `get_resources` | Get strategic and luxury resources |
| `format_state` | Get human-readable formatted game state |

### Command Tools

| Tool | Description |
|------|-------------|
| `send_action` | Send a single action/command to the game |
| `send_actions` | Send multiple actions at once |

See `python/orchestrator/MCP_README.md` for detailed tool documentation.

## Example Usage Scenarios

### 1. Opening Strategy Automation

```python
# Get game state
state = client.get_game_state()

# Analyze and decide opening
if state['era'] == 'ANCIENT':
    client.send_actions([
        {"research": "TECH_POTTERY"},
        {"policy": "POLICY_TRADITION"},
        {"city_orders": [{"city_id": 1, "order": "UNIT_SCOUT"}]}
    ], notes="Ancient era opening")
```

### 2. City Production Management

```python
# Get cities
cities = client.get_cities()

# Assign production for each city
for city in cities['cities']:
    if city['population'] >= 3 and 'BUILDING_LIBRARY' not in city['buildings']:
        client.send_action(
            {"city_orders": [{"city_id": city['id'], "order": "BUILDING_LIBRARY"}]},
            notes=f"Building library in city {city['id']}"
        )
```

### 3. Military Unit Control

```python
# Get all units
units = client.get_units()

# Move scouts to explore
for unit in units['units']:
    if unit['type'] == 'UNIT_SCOUT':
        # Move to unexplored territory
        client.send_action({
            "unit": {"id": unit['id'], "cmd": "MOVE", "to": [unit['x']+2, unit['y']]}
        }, notes=f"Exploring with scout {unit['id']}")
```

### 4. Strategic Analysis

```python
# Get comprehensive view
state = client.get_game_state()
cities = client.get_cities()
units = client.get_units()
diplomacy = client.get_diplomacy()
victory = client.get_victory_progress()

# Analyze situation
print(f"Turn {state['turn']}, Era: {state['era']}")
print(f"Cities: {cities['count']}")
print(f"Units: {units['count']}")
print(f"Victory progress: {victory}")

# Make strategic decision based on analysis
# ... (implement your strategy)
```

## Architecture

```
┌──────────────┐         ┌──────────────┐         ┌─────────────┐
│  Civ V DLL   │ ◄─────► │ Orchestrator │ ◄─────► │ MCP Server  │
│   (Game)     │  Pipe   │  (Python)    │  HTTP   │   (HTTP)    │
└──────────────┘         └──────────────┘         └─────────────┘
                                                          │
                                                          ▼
                                                   ┌─────────────┐
                                                   │  LLM Client │
                                                   │  (Claude)   │
                                                   └─────────────┘
```

**Flow:**
1. Civ V DLL sends game state via named pipe
2. Orchestrator receives and validates state
3. Orchestrator updates MCP server with latest state
4. LLM client queries state via MCP tools
5. LLM client sends actions via MCP tools
6. MCP server queues actions
7. Orchestrator merges actions and sends to DLL
8. DLL executes actions in game

## Troubleshooting

### Server won't start

**Error: `Address already in use`**
- Another process is using port 8765
- Solution: Set a different port with `MCP_HTTP_PORT=9000`

**Error: `Module not found: mcp`**
- MCP SDK not installed
- Solution: `pip install -r requirements.txt`

### No game state available

- The orchestrator hasn't connected to the Civ V DLL yet
- Make sure the game is running and the DLL is sending state
- Check that `CIVV_PIPE` matches the DLL's pipe name

### Actions not executing

- Actions are queued and sent on the next turn cycle
- Check that the DLL is accepting actions
- Verify action format matches the schema

### Connection refused (HTTP mode)

- MCP HTTP server not enabled
- Solution: Set `MCP_HTTP_ENABLED=true`
- Check that the server started successfully (look for startup message)

## Next Steps

- Read the [MCP README](../python/orchestrator/MCP_README.md) for detailed API documentation
- Explore [example scripts](../python/examples/mcp_client_example.py)
- Check the [game state design notes](game-state-info.md) for understanding available data
- Experiment with different strategies and automation

## Development

### Running in Debug Mode

View game state messages without processing:

```bash
python -m orchestrator --debug --raw
```

### Testing Without Game

Test the MCP server without connecting to the game:

```bash
# Start standalone HTTP server
python -m orchestrator.mcp_http_server

# In another terminal, run examples
python examples/mcp_client_example.py 4
```

### Custom Integration

You can also integrate the MCP server into your own Python code:

```python
from orchestrator.mcp_http_server import MCPHTTPServer

server = MCPHTTPServer(host="localhost", port=8765)
server.start()

# Update with game state
server.update_state({
    "kind": "state",
    "category": "game_level",
    "data": {...}
})

# Get queued actions
actions = server.get_pending_actions()
```

## License

Part of the llm-civ-test project.
