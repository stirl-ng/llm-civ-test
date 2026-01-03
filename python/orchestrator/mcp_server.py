"""
MCP Server for Civilization V LLM Orchestrator

Provides tools for LLMs to:
- Query game state (from turn manager's cache)
- Send actions to DLL (via turn manager, blocking)
- End turn when done deciding

The turn manager handles the actual DLL communication.
"""

import logging
from typing import Any, Optional, TYPE_CHECKING

from .formatting import format_game_state

if TYPE_CHECKING:
    from .turn_manager import TurnManager

logger = logging.getLogger(__name__)


# Tool definitions for documentation/discovery
AVAILABLE_TOOLS = [
    {
        "name": "get_game_state",
        "description": "Get the current game state. Optionally filter by category.",
        "parameters": {"category": "optional string", "format": "optional: json|human_readable"},
    },
    {
        "name": "send_action",
        "description": "Execute a game action. Blocks until DLL responds with result.",
        "parameters": {"action": "required object", "notes": "optional string"},
    },
    {
        "name": "get_cities",
        "description": "Get detailed information about all cities.",
        "parameters": {"city_id": "optional int"},
    },
    {
        "name": "get_units",
        "description": "Get information about all units.",
        "parameters": {"unit_id": "optional int"},
    },
    {
        "name": "get_tech_tree",
        "description": "Get technology tree status.",
        "parameters": {},
    },
    {
        "name": "get_diplomacy",
        "description": "Get diplomatic status with all known civilizations.",
        "parameters": {},
    },
    {
        "name": "get_available_choices",
        "description": "Get all pending decisions (tech, policy, production, etc.)",
        "parameters": {},
    },
    {
        "name": "get_victory_progress",
        "description": "Get progress toward all victory conditions.",
        "parameters": {},
    },
    {
        "name": "get_resources",
        "description": "Get strategic and luxury resources.",
        "parameters": {},
    },
    {
        "name": "format_state",
        "description": "Get a human-readable formatted version of the game state.",
        "parameters": {"raw": "optional bool"},
    },
    {
        "name": "get_state_refresh",
        "description": "Force a full state refresh from the DLL.",
        "parameters": {},
    },
    {
        "name": "end_turn",
        "description": "Signal that you are done. Actions are sent to DLL and turn advances.",
        "parameters": {"notes": "optional string"},
    },
]


class CivMCPServer:
    """Tool executor that bridges LLM requests to Civ V via turn manager."""

    def __init__(self, turn_manager: "TurnManager"):
        """Initialize MCP server.

        Args:
            turn_manager: TurnManager instance for DLL communication
        """
        self.turn_manager = turn_manager

    @property
    def current_state(self) -> Optional[dict[str, Any]]:
        """Get current game state from turn manager."""
        return self.turn_manager.current_state

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return results."""

        # Query tools - read from cache
        if name == "get_game_state":
            return self._get_game_state(
                category=arguments.get("category"),
                format_type=arguments.get("format", "json")
            )

        elif name == "get_cities":
            return self._get_cities(city_id=arguments.get("city_id"))

        elif name == "get_units":
            return self._get_units(unit_id=arguments.get("unit_id"))

        elif name == "get_tech_tree":
            return self._get_tech_tree()

        elif name == "get_diplomacy":
            return self._get_diplomacy()

        elif name == "get_available_choices":
            return self._get_available_choices()

        elif name == "get_victory_progress":
            return self._get_victory_progress()

        elif name == "get_resources":
            return self._get_resources()

        elif name == "format_state":
            return self._format_state(raw=arguments.get("raw", False))

        # Action tools - forward to DLL via turn manager
        elif name == "send_action":
            action = arguments.get("action")
            if not action:
                return {"success": False, "error": "Missing 'action' parameter"}
            return self._send_action(action, notes=arguments.get("notes", ""))

        elif name == "get_state_refresh":
            return self._get_state_refresh()

        # Turn control
        elif name == "end_turn":
            return self._end_turn(notes=arguments.get("notes", ""))

        else:
            return {"error": f"Unknown tool: {name}"}

    def _send_action(self, action: dict[str, Any], notes: str = "") -> dict[str, Any]:
        """Execute an action via DLL and return result."""
        if not self.turn_manager.turn_active:
            return {"success": False, "error": "No active turn - cannot execute action"}

        logger.info(f"Executing action: {action.get('kind', 'unknown')}")

        # Forward to turn manager (blocks until DLL responds)
        result = self.turn_manager.execute_action(action)

        if notes:
            result["notes"] = notes

        return result

    def _get_state_refresh(self) -> dict[str, Any]:
        """Force full state refresh from DLL."""
        return self.turn_manager.request_state_refresh()

    def _end_turn(self, notes: str = "") -> dict[str, Any]:
        """End the current turn."""
        if not self.turn_manager.turn_active:
            return {"success": False, "error": "No active turn to end"}

        logger.info(f"Ending turn{': ' + notes if notes else ''}")
        return self.turn_manager.end_turn(notes)

    # Query methods - read from cached state

    def _get_game_state(self, category: Optional[str] = None, format_type: str = "json") -> dict[str, Any]:
        """Get current game state, optionally filtered by category."""
        state = self.current_state
        if not state:
            return {"error": "No game state available - wait for your turn"}

        if category:
            if category in state:
                state = {category: state[category]}
            else:
                return {"error": f"Category '{category}' not found", "available": list(state.keys())}

        if format_type == "human_readable":
            formatted = format_game_state(state)
            return {"formatted": formatted, "json": state}

        return state

    def _get_cities(self, city_id: Optional[int] = None) -> dict[str, Any]:
        """Get city information."""
        state = self.current_state
        if not state:
            return {"error": "No game state available"}

        cities = state.get("cities", [])

        if city_id is not None:
            city = next((c for c in cities if c.get("id") == city_id), None)
            if city:
                return city
            return {"error": f"City {city_id} not found"}

        return {"cities": cities, "count": len(cities)}

    def _get_units(self, unit_id: Optional[int] = None) -> dict[str, Any]:
        """Get unit information."""
        state = self.current_state
        if not state:
            return {"error": "No game state available"}

        units = state.get("units", [])

        if unit_id is not None:
            unit = next((u for u in units if u.get("id") == unit_id), None)
            if unit:
                return unit
            return {"error": f"Unit {unit_id} not found"}

        return {"units": units, "count": len(units)}

    def _get_tech_tree(self) -> dict[str, Any]:
        """Get technology tree information."""
        state = self.current_state
        if not state:
            return {"error": "No game state available"}

        return state.get("technologies", state.get("technology", {}))

    def _get_diplomacy(self) -> dict[str, Any]:
        """Get diplomacy information."""
        state = self.current_state
        if not state:
            return {"error": "No game state available"}

        return state.get("diplomacy", {})

    def _get_available_choices(self) -> dict[str, Any]:
        """Get all pending choices/decisions."""
        state = self.current_state
        if not state:
            return {"error": "No game state available"}

        pending = state.get("pending_decisions", {})
        if pending:
            return {"pending_choices": pending, "has_choices": True}

        # Fallback: check legacy fields
        choices = {}
        if state.get("needs_tech_choice"):
            choices["tech"] = state.get("available_techs", [])
        if state.get("needs_policy_choice"):
            choices["policy"] = state.get("available_policies", [])
        if state.get("needs_production_choice"):
            choices["production"] = state.get("cities_needing_production", [])

        return {"pending_choices": choices, "has_choices": len(choices) > 0}

    def _get_victory_progress(self) -> dict[str, Any]:
        """Get victory condition progress."""
        state = self.current_state
        if not state:
            return {"error": "No game state available"}

        return {
            "victory_conditions": state.get("victory_conditions", []),
            "victory_progress": state.get("victory_progress", {})
        }

    def _get_resources(self) -> dict[str, Any]:
        """Get resource information."""
        state = self.current_state
        if not state:
            return {"error": "No game state available"}

        return state.get("resources", {
            "strategic": state.get("strategic_resources", {}),
            "luxury": state.get("luxury_resources", {}),
        })

    def _format_state(self, raw: bool = False) -> dict[str, Any]:
        """Get formatted game state."""
        state = self.current_state
        if not state:
            return {"error": "No game state available"}

        formatted = format_game_state(state)

        if raw:
            return {"formatted": formatted, "raw": state}

        return {"formatted": formatted}
