"""
Example MCP Client for Civilization V

This demonstrates how to interact with the MCP HTTP server
to control the game programmatically or via LLM.
"""

import json
import requests
from typing import Any, Dict


class CivMCPClient:
    """Simple client for the Civ V MCP HTTP server."""

    def __init__(self, base_url: str = "http://localhost:8765"):
        self.base_url = base_url

    def health_check(self) -> dict:
        """Check if the server is running."""
        response = requests.get(f"{self.base_url}/health")
        return response.json()

    def get_state(self) -> dict:
        """Get the current game state."""
        response = requests.get(f"{self.base_url}/state")
        return response.json()

    def call_tool(self, tool: str, arguments: dict) -> dict:
        """Call an MCP tool."""
        response = requests.post(
            f"{self.base_url}/tool",
            json={"tool": tool, "arguments": arguments}
        )
        return response.json()

    def get_game_state(self, category: str = None, format: str = "json") -> dict:
        """Get game state, optionally filtered by category."""
        return self.call_tool("get_game_state", {
            "category": category,
            "format": format
        })

    def send_action(self, action: dict, notes: str = "") -> dict:
        """Send a single action to the game."""
        return self.call_tool("send_action", {
            "action": action,
            "notes": notes
        })

    def send_actions(self, actions: list, notes: str = "") -> dict:
        """Send multiple actions to the game."""
        return self.call_tool("send_actions", {
            "actions": actions,
            "notes": notes
        })

    def get_cities(self, city_id: int = None) -> dict:
        """Get city information."""
        args = {}
        if city_id is not None:
            args["city_id"] = city_id
        return self.call_tool("get_cities", args)

    def get_units(self, unit_id: int = None) -> dict:
        """Get unit information."""
        args = {}
        if unit_id is not None:
            args["unit_id"] = unit_id
        return self.call_tool("get_units", args)

    def get_tech_tree(self) -> dict:
        """Get technology tree information."""
        return self.call_tool("get_tech_tree", {})

    def get_diplomacy(self) -> dict:
        """Get diplomacy information."""
        return self.call_tool("get_diplomacy", {})

    def get_available_choices(self) -> dict:
        """Get pending decisions."""
        return self.call_tool("get_available_choices", {})

    def get_victory_progress(self) -> dict:
        """Get victory progress."""
        return self.call_tool("get_victory_progress", {})

    def format_state(self, raw: bool = False) -> dict:
        """Get formatted game state."""
        return self.call_tool("format_state", {"raw": raw})


def example_opening_strategy():
    """Example: Execute an opening strategy."""
    client = CivMCPClient()

    # Check server is running
    print("Checking server health...")
    health = client.health_check()
    print(f"Server status: {health['status']}")
    print()

    # Get current game state
    print("Getting game state...")
    state = client.get_game_state(category="game_level")
    print(f"Current turn: {state.get('turn', 'unknown')}")
    print(f"Era: {state.get('era', 'unknown')}")
    print()

    # Get available techs
    print("Getting tech tree...")
    tech_tree = client.get_tech_tree()
    print(f"Tech tree: {json.dumps(tech_tree, indent=2)}")
    print()

    # Execute opening strategy
    print("Executing opening strategy...")
    result = client.send_actions([
        {"research": "TECH_POTTERY"},
        {"policy": "POLICY_TRADITION"},
        {"city_orders": [{"city_id": 1, "order": "UNIT_SCOUT"}]}
    ], notes="Standard opening: pottery + tradition + scout")

    print(f"Actions queued: {result}")
    print()


def example_unit_control():
    """Example: Control military units."""
    client = CivMCPClient()

    # Get all units
    print("Getting units...")
    units_data = client.get_units()
    units = units_data.get("units", [])
    print(f"Found {len(units)} units")
    print()

    # Move each military unit
    actions = []
    for unit in units:
        if unit.get("type") in ["UNIT_WARRIOR", "UNIT_SCOUT", "UNIT_ARCHER"]:
            print(f"Moving unit {unit['id']} ({unit['type']})")
            actions.append({
                "unit": {
                    "id": unit["id"],
                    "cmd": "MOVE",
                    "to": [unit["x"] + 1, unit["y"]]  # Move east
                }
            })

    if actions:
        result = client.send_actions(actions, notes="Moving military units east")
        print(f"Sent {len(actions)} unit commands")
    else:
        print("No military units to move")
    print()


def example_city_management():
    """Example: Manage city production."""
    client = CivMCPClient()

    # Get pending production choices
    print("Getting pending choices...")
    choices = client.get_available_choices()
    pending = choices.get("pending_choices", {})
    print(f"Pending choices: {json.dumps(pending, indent=2)}")
    print()

    # Get all cities
    print("Getting cities...")
    cities_data = client.get_cities()
    cities = cities_data.get("cities", [])
    print(f"Found {len(cities)} cities")
    print()

    # Assign production based on city needs
    actions = []
    for city in cities:
        city_id = city.get("id")
        population = city.get("population", 0)
        buildings = city.get("buildings", [])

        # Decision logic
        if "BUILDING_LIBRARY" not in buildings and population >= 3:
            order = "BUILDING_LIBRARY"
        elif city.get("worker_count", 0) < 2:
            order = "UNIT_WORKER"
        else:
            order = "UNIT_SETTLER"

        print(f"City {city_id}: Queuing {order}")
        actions.append({
            "city_orders": [{"city_id": city_id, "order": order}]
        })

    if actions:
        result = client.send_actions(actions, notes="City production assignments")
        print(f"Sent {len(actions)} production orders")
    print()


def example_formatted_state():
    """Example: Get human-readable game state."""
    client = CivMCPClient()

    print("Getting formatted game state...")
    result = client.format_state(raw=False)
    formatted = result.get("result", {}).get("formatted", "")

    print("=" * 60)
    print(formatted)
    print("=" * 60)


if __name__ == "__main__":
    import sys

    print("Civilization V MCP Client Examples")
    print("=" * 60)
    print()

    examples = {
        "1": ("Opening Strategy", example_opening_strategy),
        "2": ("Unit Control", example_unit_control),
        "3": ("City Management", example_city_management),
        "4": ("Formatted State", example_formatted_state),
    }

    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        print("Available examples:")
        for key, (name, _) in examples.items():
            print(f"  {key}: {name}")
        print()
        choice = input("Select example (1-4): ")

    if choice in examples:
        name, func = examples[choice]
        print(f"Running: {name}")
        print("-" * 60)
        try:
            func()
        except requests.exceptions.ConnectionError:
            print("ERROR: Could not connect to MCP server")
            print("Make sure the server is running:")
            print("  MCP_HTTP_ENABLED=true python -m orchestrator")
        except Exception as e:
            print(f"ERROR: {e}")
    else:
        print(f"Invalid choice: {choice}")
