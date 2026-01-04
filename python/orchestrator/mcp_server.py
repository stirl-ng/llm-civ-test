"""
MCP Server for Civilization V LLM Orchestrator

Provides tools for LLMs to:
- Query game state (cached from turn start)
- Send actions immediately to the DLL (synchronous, with response)
- End their turn when done deciding

Each action is sent immediately to the DLL and the response is returned
to the LLM, allowing it to see the result before deciding the next action.
"""

import logging
import threading
from typing import TYPE_CHECKING, Any, Optional

from .formatting import format_game_state

if TYPE_CHECKING:
    from .pipe_server import PipeConnection

logger = logging.getLogger(__name__)


def _validate_action(action: Any) -> tuple[bool, Optional[str]]:
    """Validate that an action is properly formatted.
    
    Args:
        action: The action to validate
        
    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    if not isinstance(action, dict):
        return False, f"Action must be a dictionary, got {type(action).__name__}"
    
    if not action:
        return False, "Action cannot be empty"
    
    # Check for required 'kind' field (common action pattern)
    if "kind" not in action:
        # Not all actions require 'kind', but log a warning for debugging
        logger.debug(f"Action missing 'kind' field: {action}")
    
    return True, None


def _merge_state_delta(base_state: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """Merge a state delta into the base state.
    
    Handles nested dictionaries by merging recursively.
    Lists are replaced entirely (no merging).
    
    Args:
        base_state: The current state to update
        delta: The state delta to apply
        
    Returns:
        New merged state (does not modify base_state)
    """
    result = base_state.copy()
    
    for key, value in delta.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursively merge nested dictionaries
            result[key] = _merge_state_delta(result[key], value)
        else:
            # Replace or add the value
            result[key] = value
    
    return result


# Tool definitions for documentation/discovery
AVAILABLE_TOOLS = [
    {
        "name": "get_game_state",
        "description": "Get the current game state. Optionally filter by category.",
        "parameters": ["category", "format"],
    },
    {
        "name": "send_action",
        "description": "Send an action to the game immediately and get the result.",
        "parameters": ["action"],
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
        "description": "Signal that you are done with your turn.",
        "parameters": ["notes"],
    },
    {
        "name": "get_notifications",
        "description": "Get unacknowledged notifications from the DLL.",
        "parameters": [],
    },
    {
        "name": "acknowledge_notification",
        "description": "Mark a notification as acknowledged.",
        "parameters": ["notification_id"],
    },
    {
        "name": "get_state_history",
        "description": "Get recent game state history from the database.",
        "parameters": ["limit"],
    },
]


class CivMCPServer:
    """Tool executor that bridges LLM requests to Civ V game.

    Sequential turn flow:
    1. Orchestrator calls start_turn(state, pipe_connection)
    2. LLM queries state and sends actions via tools
    3. Each action is sent immediately to DLL, response returned to LLM
    4. LLM calls end_turn when done
    5. Orchestrator resumes, signals DLL to advance turn
    """

    def __init__(
        self,
        turn_timeout: float = 300.0,
        state_db: Optional[Any] = None,
        notification_handler: Optional[Any] = None
    ):
        """Initialize the MCP server.

        Args:
            turn_timeout: Max seconds to wait for LLM to end turn (default 5 min)
            state_db: Optional StateDatabase instance for persistence
            notification_handler: Optional NotificationHandler instance
        """
        self.current_state: Optional[dict[str, Any]] = None
        self.turn_timeout = turn_timeout

        # Pipe connection for sending actions (set during turn)
        self._pipe_conn: Optional["PipeConnection"] = None

        # Turn management
        self._turn_active = False
        self._turn_ended = threading.Event()
        self._turn_notes: str = ""
        self._current_turn_number: Optional[int] = None  # Track which turn is active
        self._lock = threading.Lock()
        
        # Action statistics
        self._action_count = 0
        self._action_errors = 0
        self._last_action_time: Optional[float] = None
        
        # State persistence and notifications
        self.state_db = state_db
        self.notification_handler = notification_handler

    def start_turn(self, state: dict[str, Any], pipe_conn: "PipeConnection") -> None:
        """Start a new turn with the given game state and pipe connection.

        If a turn is already active, it will be cancelled (e.g., user manually advanced turn).

        Args:
            state: Game state from DLL
            pipe_conn: PipeConnection for sending actions to DLL
        """
        new_turn_num = state.get("turn")
        
        with self._lock:
            # If there's an active turn, cancel it (new turn_start arrived)
            if self._turn_active:
                old_turn = self._current_turn_number
                if new_turn_num is not None and old_turn is not None:
                    if new_turn_num > old_turn:
                        logger.warning(f"New turn_start received (turn {new_turn_num}) while turn {old_turn} was active - cancelling previous turn")
                        # Set event to cancel old turn's wait, but don't clear it yet
                        # The old turn's wait_for_turn_end() will see it and return
                        self._turn_ended.set()
                    elif new_turn_num < old_turn:
                        logger.warning(f"New turn_start received (turn {new_turn_num}) while turn {old_turn} was active - ignoring (turn already advanced)")
                        return
                    else:
                        logger.warning(f"New turn_start received (turn {new_turn_num}) while turn {old_turn} was active - ignoring (same turn)")
                        return
                else:
                    # Can't compare turn numbers, cancel anyway
                    logger.warning(f"New turn_start received while another turn was active - cancelling previous turn")
                    self._turn_ended.set()
            
            # Now set up the new turn
            self.current_state = state
            self._pipe_conn = pipe_conn
            self._turn_notes = ""
            # Clear the event for the new turn (old turn should have seen it by now)
            self._turn_ended.clear()
            self._turn_active = True
            self._current_turn_number = new_turn_num
            # Reset action statistics for new turn
            self._action_count = 0
            self._action_errors = 0
            self._last_action_time = None

        turn_num = state.get("turn", "?")
        logger.info(f"Turn {turn_num} started - waiting for LLM decisions")

    def wait_for_turn_end(self, timeout: Optional[float] = None) -> bool:
        """Block until LLM calls end_turn or timeout expires.

        Args:
            timeout: Max seconds to wait (uses self.turn_timeout if None)

        Returns:
            True if turn ended normally, False if timed out
        """
        # Remember which turn we're waiting for
        with self._lock:
            waiting_for_turn = self._current_turn_number
        
        wait_time = timeout if timeout is not None else self.turn_timeout
        ended = self._turn_ended.wait(timeout=wait_time)

        # Only deactivate if this is still the active turn (not superseded by a new turn)
        with self._lock:
            if self._current_turn_number == waiting_for_turn:
                self._turn_active = False
                self._pipe_conn = None
                self._current_turn_number = None
            else:
                # A new turn started while we were waiting, so don't deactivate
                logger.debug(f"Turn {waiting_for_turn} wait ended, but new turn {self._current_turn_number} is active - not deactivating")

        if not ended:
            logger.warning(f"Turn timed out after {wait_time}s")

        return ended

    def get_turn_notes(self) -> str:
        """Get notes from the completed turn."""
        with self._lock:
            return self._turn_notes
    
    def get_action_stats(self) -> dict[str, Any]:
        """Get statistics about actions sent during the current turn.
        
        Returns:
            Dictionary with action_count, action_errors, and last_action_time
        """
        with self._lock:
            return {
                "action_count": self._action_count,
                "action_errors": self._action_errors,
                "last_action_time": self._last_action_time,
            }
    
    def reset_action_stats(self) -> None:
        """Reset action statistics (called at turn start)."""
        with self._lock:
            self._action_count = 0
            self._action_errors = 0
            self._last_action_time = None

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return results."""

        if name == "get_game_state":
            return self._get_game_state(
                category=arguments.get("category"),
                format_type=arguments.get("format", "json")
            )

        elif name == "send_action":
            action = arguments.get("action")
            if action is None:
                return {"error": "Missing required parameter 'action'"}
            if not isinstance(action, dict):
                return {"error": f"Parameter 'action' must be a dictionary, got {type(action).__name__}"}
            return self._send_action(action=action)

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

        elif name == "get_notifications":
            return self._get_notifications()

        elif name == "acknowledge_notification":
            notification_id = arguments.get("notification_id")
            if notification_id is None:
                return {"error": "Missing required parameter 'notification_id'"}
            return self._acknowledge_notification(notification_id)

        elif name == "get_state_history":
            limit = arguments.get("limit", 10)
            if not isinstance(limit, int) or limit < 1:
                return {"error": "limit must be a positive integer"}
            return self._get_state_history(limit)

        else:
            return {"error": f"Unknown tool: {name}"}

    def _send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Send an action to the DLL immediately and return the response.
        
        Args:
            action: Action dictionary to send (must have 'kind' field typically)
            
        Returns:
            Response from DLL, or error dict if validation/execution fails
        """
        # Validate action format
        is_valid, error_msg = _validate_action(action)
        if not is_valid:
            with self._lock:
                self._action_errors += 1
            logger.warning(f"Invalid action rejected: {error_msg}")
            return {"error": error_msg, "action": action}
        
        with self._lock:
            if not self._turn_active:
                self._action_errors += 1
                return {"error": "Cannot send action - no active turn"}
            pipe_conn = self._pipe_conn
            current_turn = self._current_turn_number

        if not pipe_conn:
            with self._lock:
                self._action_errors += 1
            return {"error": "No pipe connection available"}

        import time
        action_kind = action.get("kind", "unknown")
        logger.info(f"Turn {current_turn}: Sending action '{action_kind}' to DLL: {action}")

        # Send action and get response synchronously
        try:
            response = pipe_conn.send_action({"type": "action", "action": action})
        except Exception as e:
            with self._lock:
                self._action_errors += 1
            logger.error(f"Exception sending action: {e}", exc_info=True)
            return {"error": f"Failed to send action: {e}"}

        # Check if response indicates an error
        success = not (isinstance(response, dict) and "error" in response)
        if not success:
            with self._lock:
                self._action_errors += 1
            logger.warning(f"DLL returned error for action '{action_kind}': {response.get('error')}")
        else:
            with self._lock:
                self._action_count += 1
                self._last_action_time = time.time()
        
        # Save action to database if available
        if self.state_db:
            try:
                self.state_db.save_action(
                    turn=current_turn,
                    action=action,
                    response=response if isinstance(response, dict) else None,
                    success=success
                )
            except Exception as e:
                logger.warning(f"Failed to save action to database: {e}")

        logger.debug(f"DLL response for '{action_kind}': {response}")

        # Update current state if response includes updated state or state_delta
        if isinstance(response, dict):
            with self._lock:
                if self.current_state and "state" in response:
                    # Full state update
                    self.current_state["state"] = response["state"]
                    logger.debug("Updated state from full state in response")
                elif self.current_state and "state_delta" in response:
                    # Incremental state update
                    current_state_data = self.current_state.get("state", {})
                    delta = response["state_delta"]
                    self.current_state["state"] = _merge_state_delta(current_state_data, delta)
                    logger.debug("Updated state from state_delta in response")

        return response

    def _end_turn(self, notes: str = "") -> dict[str, Any]:
        """Signal that the LLM is done with its turn."""
        with self._lock:
            if not self._turn_active:
                current_turn = self._current_turn_number
                logger.warning(f"end_turn called but no active turn (current_turn_number={current_turn})")
                return {"error": "No active turn to end"}

            self._turn_notes = notes
            pipe_conn = self._pipe_conn
            current_turn = self._current_turn_number

        # Send end_turn to DLL
        if pipe_conn:
            pipe_conn.send_end_turn()

        # Signal orchestrator that turn is done
        self._turn_ended.set()

        logger.info(f"Turn {current_turn} ended by LLM")
        return {
            "status": "turn_ended",
            "notes": notes
        }

    def _get_game_state(self, category: Optional[str] = None, format_type: str = "json") -> dict[str, Any]:
        """Get current game state, optionally filtered by category."""
        if not self.current_state:
            return {"error": "No game state available - not your turn yet"}

        state = self.current_state.get("state", {})

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
        if not self.current_state:
            return {"error": "No game state available"}

        cities = self.current_state.get("state", {}).get("cities", [])

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

        units = self.current_state.get("state", {}).get("units", [])

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

        return self.current_state.get("state", {}).get("technology", {})

    def _get_diplomacy(self) -> dict[str, Any]:
        """Get diplomacy information."""
        if not self.current_state:
            return {"error": "No game state available"}

        return self.current_state.get("state", {}).get("diplomacy", {})

    def _get_available_choices(self) -> dict[str, Any]:
        """Get all pending choices/decisions."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("state", {})
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

        data = self.current_state.get("state", {})
        return {
            "victory_conditions": data.get("victory_conditions", []),
            "victory_progress": data.get("victory_progress", {})
        }

    def _get_resources(self) -> dict[str, Any]:
        """Get resource information."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("state", {})
        return {
            "strategic": data.get("strategic_resources", {}),
            "luxury": data.get("luxury_resources", {}),
            "total": data.get("resources", {})
        }

    def _format_state(self, raw: bool = False) -> dict[str, Any]:
        """Get formatted game state."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("state", {})
        formatted = format_game_state(data)

        if raw:
            return {"formatted": formatted, "raw": data}

        return {"formatted": formatted}
    
    def _get_notifications(self) -> dict[str, Any]:
        """Get unacknowledged notifications."""
        if not self.state_db:
            return {"error": "State database not available"}
        
        notifications = self.state_db.get_unacknowledged_notifications()
        return {
            "notifications": notifications,
            "count": len(notifications)
        }
    
    def _acknowledge_notification(self, notification_id: int) -> dict[str, Any]:
        """Acknowledge a notification."""
        if not self.state_db:
            return {"error": "State database not available"}
        
        if not isinstance(notification_id, int):
            return {"error": f"notification_id must be an integer, got {type(notification_id).__name__}"}
        
        success = self.state_db.acknowledge_notification(notification_id)
        if success:
            return {"status": "acknowledged", "notification_id": notification_id}
        else:
            return {"error": f"Notification {notification_id} not found"}
    
    def _get_state_history(self, limit: int) -> dict[str, Any]:
        """Get state history from database."""
        if not self.state_db:
            return {"error": "State database not available"}
        
        history = self.state_db.get_state_history(limit=limit)
        return {
            "history": history,
            "count": len(history)
        }
