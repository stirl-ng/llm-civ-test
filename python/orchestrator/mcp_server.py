"""
MCP Server for Civilization V LLM Orchestrator

Provides tools for LLMs to:
- Query game state (cached, no DLL roundtrip)
- Send commands to queue for the DLL
- End their turn when done deciding

The orchestrator waits for the LLM to call end_turn before
sending queued actions to the DLL.
"""

import logging
import threading
from typing import Any, Optional

from .formatting import format_game_state

logger = logging.getLogger(__name__)


# Tool definitions for documentation/discovery
AVAILABLE_TOOLS = [
    {
        "name": "get_game_state",
        "description": "Get the current game state. Optionally filter by category.",
        "parameters": ["category", "format"],
    },
    {
        "name": "send_action",
        "description": "Queue an action/command for this turn.",
        "parameters": ["action", "notes"],
    },
    {
        "name": "send_actions",
        "description": "Queue multiple actions at once.",
        "parameters": ["actions", "notes"],
    },
    {
        "name": "get_cities",
        "description": "Get detailed information about all cities.",
        "parameters": ["city_id"],
    },
    {
        "name": "get_units",
        "description": "Get information about all units.",
        "parameters": ["unit_id"],
    },
    {
        "name": "get_tech_tree",
        "description": "Get technology tree status.",
        "parameters": [],
    },
    {
        "name": "get_diplomacy",
        "description": "Get diplomatic status with all known civilizations.",
        "parameters": [],
    },
    {
        "name": "get_available_choices",
        "description": "Get all pending decisions (tech, policy, production, etc.)",
        "parameters": [],
    },
    {
        "name": "get_victory_progress",
        "description": "Get progress toward all victory conditions.",
        "parameters": [],
    },
    {
        "name": "get_resources",
        "description": "Get strategic and luxury resources.",
        "parameters": [],
    },
    {
        "name": "format_state",
        "description": "Get a human-readable formatted version of the game state.",
        "parameters": ["raw"],
    },
    {
        "name": "end_turn",
        "description": "Signal that you are done with your turn. All queued actions will be sent to the game.",
        "parameters": ["notes"],
    },
]


class CivMCPServer:
    """Tool executor that bridges LLM requests to Civ V game state.

    Turn-based flow:
    1. Orchestrator calls start_turn(state) when DLL signals LLM's turn
    2. LLM queries state and queues actions via tools
    3. LLM calls end_turn when done
    4. Orchestrator calls wait_for_turn_end() which blocks until end_turn
    5. Orchestrator gets queued actions and sends to DLL
    """

    def __init__(self, turn_timeout: float = 300.0):
        """Initialize the MCP server.

        Args:
            turn_timeout: Max seconds to wait for LLM to end turn (default 5 min)
        """
        self.current_state: Optional[dict[str, Any]] = None
        self.pending_actions: list[dict[str, Any]] = []
        self.turn_timeout = turn_timeout

        # Turn management
        self._turn_active = False
        self._turn_ended = threading.Event()
        self._turn_notes: str = ""
        self._lock = threading.Lock()

    def start_turn(self, state: dict[str, Any]) -> None:
        """Start a new turn with the given game state.

        Called by orchestrator when DLL signals it's the LLM's turn.
        """
        with self._lock:
            self.current_state = state
            self.pending_actions.clear()
            self._turn_notes = ""
            self._turn_ended.clear()
            self._turn_active = True

        turn_num = state.get("data", {}).get("turn", "?")
        logger.info(f"Turn {turn_num} started - waiting for LLM decisions")

    def wait_for_turn_end(self, timeout: Optional[float] = None) -> bool:
        """Block until LLM calls end_turn or timeout expires.

        Args:
            timeout: Max seconds to wait (uses self.turn_timeout if None)

        Returns:
            True if turn ended normally, False if timed out
        """
        wait_time = timeout if timeout is not None else self.turn_timeout
        ended = self._turn_ended.wait(timeout=wait_time)

        with self._lock:
            self._turn_active = False

        if not ended:
            logger.warning(f"Turn timed out after {wait_time}s")

        return ended

    def get_turn_result(self) -> tuple[list[dict[str, Any]], str]:
        """Get the actions and notes from the completed turn.

        Returns:
            Tuple of (actions_list, notes_string)
        """
        with self._lock:
            actions = self.pending_actions[:]
            self.pending_actions.clear()
            notes = self._turn_notes
        return actions, notes

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return results."""

        if name == "get_game_state":
            return self._get_game_state(
                category=arguments.get("category"),
                format_type=arguments.get("format", "json")
            )

        elif name == "send_action":
            return self._send_action(
                action=arguments.get("action", {}),
                notes=arguments.get("notes", "")
            )

        elif name == "send_actions":
            return self._send_actions(
                actions=arguments.get("actions", []),
                notes=arguments.get("notes", "")
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

        elif name == "end_turn":
            return self._end_turn(notes=arguments.get("notes", ""))

        else:
            return {"error": f"Unknown tool: {name}"}

    def _end_turn(self, notes: str = "") -> dict[str, Any]:
        """Signal that the LLM is done with its turn."""
        with self._lock:
            if not self._turn_active:
                return {"error": "No active turn to end"}

            self._turn_notes = notes
            action_count = len(self.pending_actions)
            self._turn_ended.set()

        logger.info(f"Turn ended by LLM with {action_count} queued actions")
        return {
            "status": "turn_ended",
            "actions_queued": action_count,
            "notes": notes
        }

    def _get_game_state(self, category: Optional[str] = None, format_type: str = "json") -> dict[str, Any]:
        """Get current game state, optionally filtered by category."""
        if not self.current_state:
            return {"error": "No game state available - not your turn yet"}

        state = self.current_state.get("data", {})

        if category:
            if category in state:
                state = {category: state[category]}
            else:
                return {"error": f"Category '{category}' not found", "available": list(state.keys())}

        if format_type == "human_readable":
            formatted = format_game_state(state)
            return {"formatted": formatted, "json": state}

        return state

    def _send_action(self, action: dict[str, Any], notes: str = "") -> dict[str, Any]:
        """Queue a single action to be sent to the game."""
        with self._lock:
            if not self._turn_active:
                return {"error": "Cannot queue actions - no active turn"}
            self.pending_actions.append(action)
            count = len(self.pending_actions)

        logger.info(f"Action queued: {action}")
        return {
            "status": "queued",
            "action": action,
            "notes": notes,
            "total_pending": count
        }

    def _send_actions(self, actions: list[dict[str, Any]], notes: str = "") -> dict[str, Any]:
        """Queue multiple actions to be sent to the game."""
        with self._lock:
            if not self._turn_active:
                return {"error": "Cannot queue actions - no active turn"}
            self.pending_actions.extend(actions)
            count = len(self.pending_actions)

        logger.info(f"{len(actions)} actions queued")
        return {
            "status": "queued",
            "action_count": len(actions),
            "notes": notes,
            "total_pending": count
        }

    def _get_cities(self, city_id: Optional[int] = None) -> dict[str, Any]:
        """Get city information."""
        if not self.current_state:
            return {"error": "No game state available"}

        cities = self.current_state.get("data", {}).get("cities", [])

        if city_id is not None:
            city = next((c for c in cities if c.get("id") == city_id), None)
            if city:
                return city
            return {"error": f"City {city_id} not found"}

        return {"cities": cities, "count": len(cities)}

    def _get_units(self, unit_id: Optional[int] = None) -> dict[str, Any]:
        """Get unit information."""
        if not self.current_state:
            return {"error": "No game state available"}

        units = self.current_state.get("data", {}).get("units", [])

        if unit_id is not None:
            unit = next((u for u in units if u.get("id") == unit_id), None)
            if unit:
                return unit
            return {"error": f"Unit {unit_id} not found"}

        return {"units": units, "count": len(units)}

    def _get_tech_tree(self) -> dict[str, Any]:
        """Get technology tree information."""
        if not self.current_state:
            return {"error": "No game state available"}

        return self.current_state.get("data", {}).get("technology", {})

    def _get_diplomacy(self) -> dict[str, Any]:
        """Get diplomacy information."""
        if not self.current_state:
            return {"error": "No game state available"}

        return self.current_state.get("data", {}).get("diplomacy", {})

    def _get_available_choices(self) -> dict[str, Any]:
        """Get all pending choices/decisions."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("data", {})
        choices = {}

        if data.get("needs_tech_choice"):
            choices["tech"] = data.get("available_techs", [])

        if data.get("needs_policy_choice"):
            choices["policy"] = data.get("available_policies", [])

        if data.get("needs_production_choice"):
            choices["production"] = data.get("cities_needing_production", [])

        if data.get("needs_religion_choice"):
            choices["religion"] = data.get("religion_options", {})

        if data.get("needs_trade_route_assignment"):
            choices["trade_routes"] = data.get("available_trade_routes", [])

        return {"pending_choices": choices, "has_choices": len(choices) > 0}

    def _get_victory_progress(self) -> dict[str, Any]:
        """Get victory condition progress."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("data", {})
        return {
            "victory_conditions": data.get("victory_conditions", []),
            "victory_progress": data.get("victory_progress", {})
        }

    def _get_resources(self) -> dict[str, Any]:
        """Get resource information."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("data", {})
        return {
            "strategic": data.get("strategic_resources", {}),
            "luxury": data.get("luxury_resources", {}),
            "total": data.get("resources", {})
        }

    def _format_state(self, raw: bool = False) -> dict[str, Any]:
        """Get formatted game state."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("data", {})
        formatted = format_game_state(data)

        if raw:
            return {"formatted": formatted, "raw": data}

        return {"formatted": formatted}
