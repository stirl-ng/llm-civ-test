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

# Custom turn timeout (default 300 seconds)
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

**End turn:**
```bash
curl -X POST http://localhost:8765/tool \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "end_turn",
    "arguments": {"notes": "Finished turn decisions"}
  }'
```

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

### Action Tools

| Tool | Description |
|------|-------------|
| `send_action` | Send an action to the game immediately and get the result |

### Turn Control

| Tool | Description |
|------|-------------|
| `end_turn` | Signal that you are done with your turn |

## Sequential Action Flow

The MCP server uses a **sequential action flow**:

1. LLM calls `send_action` with an action
2. Action is sent immediately to the DLL
3. DLL executes the action and returns a response
4. Response is returned to the LLM
5. LLM can see the result before deciding the next action
6. Repeat until LLM calls `end_turn`

This allows the LLM to react to the results of each action, making more intelligent decisions.

## Example Usage Scenarios

### 1. Opening Strategy

```python
import requests

BASE_URL = "http://localhost:8765"

def call_tool(tool: str, arguments: dict = None):
    response = requests.post(f"{BASE_URL}/tool", json={
        "tool": tool,
        "arguments": arguments or {}
    })
    return response.json()

# Get game state
state = call_tool("get_game_state")
print(f"Turn {state.get('turn')}")

# Research pottery
result = call_tool("send_action", {"action": {"kind": "research", "tech": "TECH_POTTERY"}})
print(f"Research result: {result}")

# Adopt tradition policy
result = call_tool("send_action", {"action": {"kind": "policy", "policy": "POLICY_TRADITION"}})
print(f"Policy result: {result}")

# End turn
call_tool("end_turn", {"notes": "Ancient era opening"})
```

### 2. City Production Management

```python
# Get cities
cities = call_tool("get_cities")

for city in cities.get("cities", []):
    city_id = city.get("id")
    # Set production to library
    result = call_tool("send_action", {
        "action": {"kind": "production", "city_id": city_id, "item": "BUILDING_LIBRARY"}
    })
    print(f"City {city_id} production: {result}")
```

### 3. Unit Movement

```python
# Get all units
units = call_tool("get_units")

for unit in units.get("units", []):
    if unit.get("type") == "UNIT_SCOUT":
        result = call_tool("send_action", {
            "action": {
                "kind": "move_unit",
                "unit_id": unit["id"],
                "to": [unit["x"] + 2, unit["y"]]
            }
        })
        print(f"Scout {unit['id']} move: {result}")
```

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
2. Orchestrator caches state and waits for LLM
3. LLM queries state via HTTP (reads from cache)
4. LLM sends action via HTTP
5. Orchestrator forwards action to DLL immediately
6. DLL executes action and returns result
7. Result returned to LLM
8. LLM can send more actions or call `end_turn`
9. Orchestrator sends `end_turn` to DLL
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
