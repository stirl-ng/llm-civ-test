# Civilization V MCP Server

An MCP (Model Context Protocol) server that exposes the Civilization V game state and control interface to LLMs.

## Overview

This MCP server allows AI assistants like Claude to:
- **Query game state**: Get detailed information about the current game
- **Control the game**: Send commands to units, cities, and manage research/policies
- **Make strategic decisions**: Access victory progress, diplomacy, resources, etc.

## Quick Start

### 1. Install Dependencies

```bash
cd python
pip install -r requirements.txt
```

### 2. Run the MCP Server

```bash
python -m orchestrator --mcp
```

The server will start and listen on stdio for MCP protocol messages.

### 3. Connect from an LLM Client

Configure your LLM client (Claude Desktop, etc.) to connect to the MCP server:

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

## Available Tools

### State Queries

#### `get_game_state`
Get the current game state, optionally filtered by category.

**Parameters:**
- `category` (optional): Filter by category (e.g., "game_level", "cities", "units", "technology", "diplomacy")
- `format` (optional): Output format - "json" or "human_readable"

**Example:**
```json
{
  "category": "game_level",
  "format": "json"
}
```

#### `get_cities`
Get detailed information about cities.

**Parameters:**
- `city_id` (optional): Get info for specific city only

**Example:**
```json
{
  "city_id": 1
}
```

#### `get_units`
Get information about all units.

**Parameters:**
- `unit_id` (optional): Get info for specific unit only

#### `get_tech_tree`
Get technology tree status: researched techs, current research, available options.

#### `get_diplomacy`
Get diplomatic status with all known civilizations.

#### `get_available_choices`
Get all pending decisions that need to be made (tech choice, policy choice, production, etc.).

#### `get_victory_progress`
Get progress toward all victory conditions.

#### `get_resources`
Get strategic and luxury resources information.

#### `format_state`
Get a human-readable formatted version of the game state.

**Parameters:**
- `raw` (optional): Include raw JSON alongside formatted output

### Command Actions

#### `send_action`
Send a single action/command to the game.

**Parameters:**
- `action` (required): The action object
- `notes` (optional): Notes about why this action was chosen

**Example - Research:**
```json
{
  "action": {
    "research": "TECH_POTTERY"
  },
  "notes": "Starting pottery for granary access"
}
```

**Example - Unit Movement:**
```json
{
  "action": {
    "unit": {
      "id": 10,
      "cmd": "MOVE",
      "to": [6, 6]
    }
  },
  "notes": "Moving scout to explore"
}
```

**Example - City Production:**
```json
{
  "action": {
    "city_orders": [
      {
        "city_id": 1,
        "order": "UNIT_WORKER"
      }
    ]
  },
  "notes": "Building worker in capital"
}
```

#### `send_actions`
Send multiple actions at once.

**Parameters:**
- `actions` (required): Array of action objects
- `notes` (optional): Overall strategy notes

**Example:**
```json
{
  "actions": [
    {"research": "TECH_POTTERY"},
    {"policy": "POLICY_TRADITION"},
    {"city_orders": [{"city_id": 1, "order": "UNIT_WORKER"}]}
  ],
  "notes": "Opening strategy: pottery + tradition + worker"
}
```

## Action Types

### Research
```json
{"research": "TECH_POTTERY"}
```

### Policies
```json
{"policy": "POLICY_TRADITION"}
```

### City Production
```json
{
  "city_orders": [
    {"city_id": 1, "order": "UNIT_WORKER"},
    {"city_id": 2, "order": "BUILDING_MONUMENT"}
  ]
}
```

### Unit Commands

**Movement:**
```json
{
  "unit": {
    "id": 10,
    "cmd": "MOVE",
    "to": [6, 6]
  }
}
```

**Attack:**
```json
{
  "unit": {
    "id": 10,
    "cmd": "ATTACK",
    "target_unit": 12
  }
}
```

**Found City:**
```json
{
  "unit": {
    "id": 10,
    "cmd": "FOUND_CITY"
  }
}
```

## Integration with Orchestrator

The MCP server is integrated with the orchestrator and shares its configuration:

```bash
# Use custom config
python -m orchestrator --mcp --agent-config configs/custom.yaml

# Use custom pipe
python -m orchestrator --mcp --pipe "\\\\.\\pipe\\custom_pipe"
```

## Architecture

```
┌─────────────┐         ┌──────────────┐         ┌─────────┐
│ Civ V DLL   │ ◄─────► │ Orchestrator │ ◄─────► │   MCP   │
│  (Game)     │  Pipe   │   (Bridge)   │  stdio  │  Server │
└─────────────┘         └──────────────┘         └─────────┘
                                                       ▲
                                                       │
                                                       ▼
                                                  ┌─────────┐
                                                  │   LLM   │
                                                  │ Client  │
                                                  └─────────┘
```

1. **Civ V DLL** sends game state via Windows named pipe
2. **Orchestrator** receives state and makes it available to MCP server
3. **MCP Server** exposes tools to LLM clients
4. **LLM Client** (Claude, etc.) calls tools to query state and send actions
5. **Actions** flow back through the chain to the game

## State Categories

The game state is organized into these categories:

- `game_level` - Turn number, era, victory conditions, player counts
- `player` - Gold, science, culture, faith, happiness, ideology
- `technology` - Research status, available techs, current research
- `policies` - Social policy trees, adopted policies, available options
- `cities` - City details, buildings, production, population
- `units` - Unit positions, health, promotions, available commands
- `map` - Terrain, resources, visibility
- `diplomacy` - Relationships, wars, agreements, known players
- `city_states` - Alliance status, influence, quests
- `religion` - Faith, followers, religious units
- `trade_routes` - Active and available trade routes
- `wonders` - Built and building wonders
- `great_people` - Great person point progress
- `combat` - Unit strengths, combat predictions
- `victory` - Victory progress tracking
- `events` - Notifications and required decisions
- `resources` - Strategic and luxury resource availability

## Development

### Running in Debug Mode

To see what messages are being sent/received:

```bash
# Debug server (view messages only)
python -m orchestrator --debug --raw

# MCP server with debug logging
export LOG_LEVEL=DEBUG
python -m orchestrator --mcp
```

### Testing

```bash
# Test with stdio transport
echo '{"kind": "state", "category": "game_level", "data": {...}}' | python -m orchestrator --mcp --stdio
```

## Troubleshooting

### "No game state available"

The MCP server hasn't received any state from the orchestrator yet. Make sure:
1. The Civ V DLL is running and sending state
2. The pipe connection is established
3. The orchestrator is receiving messages

### "Action queued but not executing"

Actions are queued and sent back to the game on the next turn cycle. This is normal behavior.

### "Category not found in state"

The requested state category isn't available in the current game state. Use `get_game_state` without a category filter to see what's available.

## Examples

### Example: Opening Strategy

```python
# Get current game state
state = get_game_state(category="game_level", format="json")

# Check available techs
tech_tree = get_tech_tree()

# Make opening decisions
send_actions({
  "actions": [
    {"research": "TECH_POTTERY"},
    {"policy": "POLICY_TRADITION"},
    {
      "city_orders": [
        {"city_id": 1, "order": "UNIT_SCOUT"}
      ]
    }
  ],
  "notes": "Standard opening: pottery → granary, tradition for border growth, scout for exploration"
})
```

### Example: Military Strategy

```python
# Get all units
units = get_units()

# Get diplomacy status
diplomacy = get_diplomacy()

# Move units toward enemy
actions = []
for unit in units["units"]:
    if unit["type"] == "UNIT_WARRIOR":
        actions.append({
            "unit": {
                "id": unit["id"],
                "cmd": "MOVE",
                "to": [unit["x"] + 1, unit["y"]]
            }
        })

send_actions({"actions": actions, "notes": "Advancing military units"})
```

### Example: City Management

```python
# Get all cities needing production
choices = get_available_choices()

# Assign production based on city needs
actions = []
for city_id in choices["pending_choices"].get("production", []):
    city = get_cities(city_id=city_id)

    # Logic to decide what to build
    order = "UNIT_WORKER" if city["worker_count"] < 2 else "BUILDING_LIBRARY"

    actions.append({
        "city_orders": [{"city_id": city_id, "order": order}]
    })

send_actions({"actions": actions, "notes": "City production assignments"})
```

## License

Part of the llm-civ-test project.
