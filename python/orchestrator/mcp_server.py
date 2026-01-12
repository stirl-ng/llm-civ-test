"""
MCP Server for Civilization V LLM Orchestrator

Provides tools for LLMs to:
- Query game state (via DLL requests)
- Send actions immediately to the DLL (synchronous, with response)
- End their turn when done deciding

Each action is sent immediately to the DLL and the response is returned
to the LLM, allowing it to see the result before deciding the next action.
"""

import threading
import time
from typing import TYPE_CHECKING, Any, Optional


if TYPE_CHECKING:
    from .pipe_server import PipeConnection



class ToolError(Exception):
    """Raised when a tool encounters an error (param validation, missing pipe, etc.)."""
    pass


class CivMCPServer:
    """Tool executor that bridges LLM requests to Civ V game.

    Sequential turn flow:
    1. Orchestrator calls start_turn(state, pipe_connection)
    2. LLM queries state and sends actions via tools (all queries go to DLL)
    3. Each action is sent immediately to DLL, response returned to LLM
    4. LLM calls end_turn when done
    5. Orchestrator resumes, signals DLL to advance turn

    NOTE: Multiplayer considerations
    =================================
    Currently designed for single-player with one LLM client. The synchronous
    blocking design works well for this use case. If we add simultaneous
    multiplayer support in the future, we'll need to:
    1. Pass request_id from execute_tool() down to all tool handlers
    2. Ensure all tool handlers propagate request_id to DLL requests
    3. Consider async/queue-based architecture if multiple clients need
       concurrent access to the same game state
    4. Add client/session tracking to route responses correctly
    """

    def __init__(self, turn_timeout: float = 300.0):
        """Initialize the MCP server.

        Args:
            turn_timeout: Max seconds to wait for LLM to end turn (default 5 min)
        """
        self.turn_timeout = turn_timeout

        # Turn management
        self._pipe_conn: Optional["PipeConnection"] = None
        self._current_turn_number: Optional[int] = None
        self._first_turn_of_game: Optional[int] = None
        self._lock = threading.Lock()

        # Session tracking (game_id persists across saves, session_id per connection)
        self._current_game_id: Optional[int] = None
        self._current_session_id: Optional[int] = None
        self._current_player_id: Optional[int] = None

        # Action statistics
        self._action_count = 0
        self._action_errors = 0
        self._last_action_time: Optional[float] = None

        self.uptime = time.monotonic()

        # Game logger (JSONL file) - singleton, shared across all components
        from .game_logger import get_game_logger
        self._message_logger = get_game_logger()

    def get_about(self) -> dict[str, Any]:
        """Get information about the MCP server."""
        return {
            "turn_timeout": self.turn_timeout,
            "current_turn_number": self._current_turn_number,
            "action_count": self._action_count,
            "action_errors": self._action_errors,
            "last_action_time": self._last_action_time,
            "uptime": self.uptime,
        }

    def get_tools(self) -> list[dict[str, Any]]:
        """Get the tools available to the MCP server.

        Generates tool definitions from handler docstrings and _TOOLS registry.
        """
        tools = []

        # Implemented tools - description from docstring
        for name, (handler_name, params) in self._TOOLS.items():
            handler = getattr(self, handler_name, None)
            description = (handler.__doc__ or "").strip().split("\n")[0] if handler else ""
            tools.append({
                "name": name,
                "description": description,
                "parameters": params,
            })

        # Placeholder tools - description from _PLACEHOLDER_TOOLS
        for name, description in self._PLACEHOLDER_TOOLS.items():
            tools.append({
                "name": name,
                "description": description,
                "parameters": {},
            })

        return tools

    def start_turn(self, state: dict[str, Any]) -> None:
        """Update turn state with the given game state.

        Args:
            state: Game state from DLL (contains turn, player_id, game_id, session_id)
        """
        new_turn_num = state.get("turn")
        new_game_id = state.get("game_id")
        new_session_id = state.get("session_id")
        new_player_id = state.get("player_id")

        with self._lock:
            self._current_turn_number = new_turn_num
            self._current_game_id = new_game_id
            self._current_session_id = new_session_id
            self._current_player_id = new_player_id

            # Reset action statistics for new turn
            self._action_count = 0
            self._action_errors = 0
            self._last_action_time = None

    def handle_heartbeat(self, state: dict[str, Any]) -> None:
        """Handle heartbeat from DLL - updates state without resetting counters.

        This is called periodically by the DLL (every ~5 seconds) to let the orchestrator
        know the game is still connected. Useful for detecting the game after orchestrator
        restart.

        Args:
            state: Heartbeat state from DLL (contains turn, player_id, game_id, session_id)
        """
        with self._lock:
            self._current_turn_number = state.get("turn")
            self._current_game_id = state.get("game_id")
            self._current_session_id = state.get("session_id")
            self._current_player_id = state.get("player_id")

    @property
    def turn_number(self) -> Optional[int]:
        """Get the current turn number."""
        with self._lock:
            return self._current_turn_number
    
    def get_action_stats(self) -> dict[str, Any]:
        """Get statistics about actions sent during the current turn.

        Returns:
            Dictionary with action_count, action_errors, and last_action_time
        """
        with self._lock:
            return {
                "game_id": self._current_game_id,
                "session_id": self._current_session_id,
                "turn": self._current_turn_number,
                "player_id": self._current_player_id,
                "action_count": self._action_count,
                "action_errors": self._action_errors,
                "last_action_time": self._last_action_time,
            }

    @property
    def current_game_id(self) -> Optional[int]:
        """Get the current game ID (persists across saves)."""
        with self._lock:
            return self._current_game_id

    @property
    def current_session_id(self) -> Optional[int]:
        """Get the current session ID (changes per pipe connection)."""
        with self._lock:
            return self._current_session_id

    @property
    def current_player_id(self) -> Optional[int]:
        """Get the current player ID."""
        with self._lock:
            return self._current_player_id

    # -------------------------------------------------------------------------
    # Helper methods for tool implementations
    # -------------------------------------------------------------------------

    def _require_param(
        self, arguments: dict[str, Any], name: str, param_type: type
    ) -> Any:
        """Get and validate a required parameter.

        Args:
            arguments: The tool arguments dict
            name: Parameter name to extract
            param_type: Expected type (str, int, dict, etc.)

        Returns:
            The validated parameter value

        Raises:
            ToolError: If parameter is missing or wrong type
        """
        value = arguments.get(name)
        if value is None:
            raise ToolError(f"Missing required parameter '{name}'")
        if not isinstance(value, param_type):
            raise ToolError(
                f"Parameter '{name}' must be {param_type.__name__}, "
                f"got {type(value).__name__}"
            )
        return value

    def set_pipe_connection(self, pipe_conn: "PipeConnection") -> None:
        """Set the current pipe connection.

        Called by NamedPipeServer when a new client connects.

        Args:
            pipe_conn: The new PipeConnection instance
        """
        with self._lock:
            self._pipe_conn = pipe_conn

    def _get_pipe(self) -> "PipeConnection":
        """Get the pipe connection or raise if not available.

        Returns:
            The current PipeConnection

        Raises:
            ToolError: If no pipe connection is available
        """
        with self._lock:
            pipe_conn = self._pipe_conn
        if not pipe_conn:
            raise ToolError("No pipe connection available")
        return pipe_conn

    def acknowledge_response(self, response: dict[str, Any]) -> bool:
        """Deliver a response to a waiting request.

        Forwards to the current pipe connection's acknowledge_response method.

        Args:
            response: Response dictionary from DLL

        Returns:
            True if response was delivered to a waiting request, False otherwise
        """
        with self._lock:
            pipe_conn = self._pipe_conn
        if not pipe_conn:
            return False
        return pipe_conn.acknowledge_response(response)

    def _send_pipe_request(
        self, request_type: str, timeout: float = 5.0, **extra_fields: Any
    ) -> dict[str, Any]:
        """Send a request to the DLL and return the response.

        Args:
            request_type: The message type (e.g., "get_state", "get_units")
            timeout: Request timeout in seconds
            **extra_fields: Additional fields to include in the request

        Returns:
            Response dict from DLL

        Raises:
            ToolError: If no pipe connection or request fails
        """
        pipe = self._get_pipe()
        request = {"type": request_type, **extra_fields}
        try:
            return pipe.send_request(request, timeout=timeout)
        except Exception as e:
            raise ToolError(f"Request failed: {e}") from e

    def _not_implemented(self, tool_name: str) -> dict[str, Any]:
        """Return a standard 'not implemented' response for placeholder tools."""
        return {
            "status": "not_implemented",
            "message": f"Tool '{tool_name}' is not yet implemented in the DLL",
        }

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return results.

        Single log entry with both call and result after execution.
        ToolErrors are expected (validation failures) and returned cleanly.
        """
        try:
            if name in self._TOOLS:
                handler_name, _ = self._TOOLS[name]
                handler = getattr(self, handler_name)
                result = handler(arguments)

            elif name in self._PLACEHOLDER_TOOLS:
                result = self._not_implemented(name)

            else:
                raise ToolError(f"Unknown tool: {name}")
        except ToolError as e:
            result = {"error": str(e), "status": "error"}
        except Exception as e:
            result = {"error": str(e), "status": "error"}

        # Single log entry with both call and result
        self._message_logger.log_message({ # TODO is this the actual return result?
            "type": "tool_call",
            "game_id": self._current_game_id,
            "session_id": self._current_session_id,
            "player_id": self._current_player_id,
            "turn": self.turn_number,
            "tool": name,
            "arguments": arguments,
            "result": result,
        })

        return result

    # -------------------------------------------------------------------------
    # Tool Registry
    # -------------------------------------------------------------------------
    # Each tool maps to (handler_method_name, params_dict)
    # Description comes from the handler's docstring

    _TOOLS: dict[str, tuple[str, dict]] = {
        # Query tools (DLL requests)
        "get_game_state": ("_get_game_state", {"category": "optional string"}),
        "get_current_turn": ("_get_current_turn", {}),
        "get_cities": ("_get_cities", {"city_id": "optional int"}),
        "get_city_production": ("_get_city_production", {"city_id": "required int"}),
        "get_units": ("_get_units", {"player_id": "optional int"}),
        "get_notifications": ("_get_notifications", {}),
        "ping": ("_ping", {}),
        # Log tools (local)
        "get_log": ("_get_log", {
            "message_type": "optional string (e.g., 'turn_start', 'notification', 'note')",
            "direction": "optional string: 'incoming'|'outgoing'",
            "turn_number": "optional int",
            "player_id": "optional int",
            "game_id": "optional int (overrides current_game_only)",
            "session_id": "optional int",
            "current_game_only": "optional bool (default True)",
            "limit": "optional int (default 100, max 1000)",
        }),
        "add_note": ("_add_note", {"content": "required string"}),
        "delete_note": ("_delete_note", {"note_id": "required string (uuid of note to delete)"}),
        # Action tools
        "send_action": ("_send_action", {"action": "required dict with 'kind' field"}),
        "end_turn": ("_end_turn", {"turn": "required int"}),
        # Popup choice tools
        "select_pantheon": ("_select_pantheon", {
            "belief_id": "required int - ID of the belief to select",
            "player_id": "optional int - player ID (defaults to active player)"
        }),
        "found_religion": ("_found_religion", {
            "religion_id": "required int - ID of the religion to found",
            "founder_belief_id": "required int - ID of the founder belief",
            "follower_belief_id": "required int - ID of the follower belief",
            "pantheon_belief_id": "optional int - ID of pantheon belief (only if player doesn't have one)",
            "bonus_belief_id": "optional int - ID of bonus belief (for Byzantium trait)",
            "religion_name": "optional string - custom name for the religion",
            "city_x": "optional int - X coordinate of holy city",
            "city_y": "optional int - Y coordinate of holy city",
            "player_id": "optional int - player ID (defaults to active player)"
        }),
        "enhance_religion": ("_enhance_religion", {
            "follower2_belief_id": "required int - ID of the second follower belief",
            "enhancer_belief_id": "required int - ID of the enhancer belief",
            "player_id": "optional int - player ID (defaults to active player)"
        }),
        "city_capture_decision": ("_city_capture_decision", {
            "city_id": "required int - ID of the captured city",
            "action": "required string - one of: 'puppet', 'annex', 'raze', 'destroy', 'liberate'",
            "liberate_to": "optional int - player ID to liberate the city to (required for 'liberate' action)",
            "player_id": "optional int - player ID (defaults to active player)"
        }),
        "set_city_production": ("_set_city_production", {
            "city_id": "required int - ID of the city",
            "order_type": "required int - 0=TRAIN (unit), 1=CONSTRUCT (building), 2=CREATE (project), 3=MAINTAIN (process)",
            "item_id": "required int - ID of the unit/building/project/process to produce",
            "player_id": "optional int - player ID (defaults to active player)"
        }),
        "choose_tech": ("_choose_tech", {
            "tech_id": "required int - ID of the technology to research",
            "player_id": "optional int - player ID (defaults to active player)"
        }),
    }

    # Placeholder tools - description only, not yet implemented in DLL
    _PLACEHOLDER_TOOLS: dict[str, str] = {
        "get_tech_tree": "Get technology tree status.",
        "get_diplomacy": "Get diplomatic status with all known civilizations.",
        "get_available_choices": "Get all pending decisions (tech, policy, production, etc.)",
        "get_victory_progress": "Get progress toward all victory conditions.",
        "get_resources": "Get strategic and luxury resources.",
        "get_player_status": "Get detailed status information for a player.",
    }

    def _send_action(self, args: dict[str, Any]) -> dict[str, Any]:
        """Send an action to the DLL and return the response."""
        action = self._require_param(args, "action", dict)

        # Validate action has required 'kind' field
        if not action:
            with self._lock:
                self._action_errors += 1
            raise ToolError("Action cannot be empty")
        if "kind" not in action:
            with self._lock:
                self._action_errors += 1
            raise ToolError("Action missing required 'kind' field")

        pipe = self._get_pipe()
        action_kind = action["kind"]

        # Convert action to message: 'kind' -> 'type'
        message = {k: v for k, v in action.items() if k != "kind"}
        message["type"] = action_kind

        # Send and track stats
        try:
            result = pipe.send_request(message, timeout=10.0)
            with self._lock:
                if "error" in result:
                    self._action_errors += 1
                else:
                    self._action_count += 1
                    self._last_action_time = time.time()
            return result
        except Exception as e:
            with self._lock:
                self._action_errors += 1
            raise ToolError(f"Failed to send action: {e}") from e

    def _end_turn(self, args: dict[str, Any]) -> dict[str, Any]:
        """Signal that the LLM is done with its turn and wait for DLL confirmation.

        The DLL might block the end-turn request if there are pending units,
        tech choices, etc. This method waits for the authoritative result.
        """
        turn = self._require_param(args, "turn", int)
        with self._lock:
            pipe_conn = self._pipe_conn
            current_turn = self._current_turn_number

        if not pipe_conn:
            return {"error": "No pipe connection available", "status": "error"}

        # Validate that we have a current turn number set
        if current_turn is None:
            return {
                "error": "No active turn - turn_start has not been received yet",
                "status": "error",
                "requested_turn": turn,
                "current_turn": None,
                "message": "Cannot end turn: no turn has been started. Wait for turn_start message from DLL."
            }

        # Validate turn matches current turn
        if turn != current_turn:
            return {
                "error": f"Turn mismatch: requested turn {turn} but current turn is {current_turn}",
                "status": "error",
                "requested_turn": turn,
                "current_turn": current_turn,
                "message": f"Turn number mismatch. You requested to end turn {turn}, but the current turn is {current_turn}."
            }

        # Send end_turn to DLL and wait for end_turn_result
        try:
            msg = {"type": "end_turn", "turn": turn}
            result = pipe_conn.send_request(msg, timeout=15.0)
            return result

        except Exception as e:
            return {"status": "error", "error": f"Failed to end turn: {e}"}

    # -------------------------------------------------------------------------
    # Popup Choice Tools
    # -------------------------------------------------------------------------

    def _select_pantheon(self, args: dict[str, Any]) -> dict[str, Any]:
        """Select a pantheon belief for the player.

        Use this when the game shows a 'choose_pantheon' popup. The available
        beliefs and their IDs are sent via the popup_choice_needed message.
        """
        belief_id = self._require_param(args, "belief_id", int)
        player_id = args.get("player_id")

        pipe = self._get_pipe()
        message = {"type": "select_pantheon", "belief_id": belief_id}
        if player_id is not None:
            message["player_id"] = player_id

        try:
            return pipe.send_request(message, timeout=10.0)
        except Exception as e:
            return {"status": "error", "error": f"Failed to select pantheon: {e}"}

    def _found_religion(self, args: dict[str, Any]) -> dict[str, Any]:
        """Found a new religion for the player.

        Use this when the game shows a 'found_religion' popup. The available
        religions and beliefs are sent via the popup_choice_needed message.
        """
        religion_id = self._require_param(args, "religion_id", int)
        founder_belief_id = self._require_param(args, "founder_belief_id", int)
        follower_belief_id = self._require_param(args, "follower_belief_id", int)

        pipe = self._get_pipe()
        message: dict[str, Any] = {
            "type": "found_religion",
            "religion_id": religion_id,
            "founder_belief_id": founder_belief_id,
            "follower_belief_id": follower_belief_id,
        }
        for key in ("pantheon_belief_id", "bonus_belief_id", "religion_name", "city_x", "city_y", "player_id"):
            if args.get(key) is not None:
                message[key] = args[key]

        try:
            return pipe.send_request(message, timeout=10.0)
        except Exception as e:
            return {"status": "error", "error": f"Failed to found religion: {e}"}

    def _enhance_religion(self, args: dict[str, Any]) -> dict[str, Any]:
        """Enhance an existing religion with additional beliefs.

        Use this when the game shows an 'enhance_religion' popup. The available
        beliefs are sent via the popup_choice_needed message.
        """
        follower2_belief_id = self._require_param(args, "follower2_belief_id", int)
        enhancer_belief_id = self._require_param(args, "enhancer_belief_id", int)

        pipe = self._get_pipe()
        message: dict[str, Any] = {
            "type": "enhance_religion",
            "follower2_belief_id": follower2_belief_id,
            "enhancer_belief_id": enhancer_belief_id,
        }
        if args.get("player_id") is not None:
            message["player_id"] = args["player_id"]

        try:
            return pipe.send_request(message, timeout=10.0)
        except Exception as e:
            return {"status": "error", "error": f"Failed to enhance religion: {e}"}

    def _city_capture_decision(self, args: dict[str, Any]) -> dict[str, Any]:
        """Make a decision about a captured city.

        Use this when the game shows a 'city_capture' popup. The available
        actions are sent via the popup_choice_needed message.

        Actions:
        - puppet: Make the city a puppet (limited control, no unhappiness penalty)
        - annex: Annex the city (full control, but adds unhappiness)
        - raze: Raze the city to the ground (city is destroyed over time)
        - destroy: Destroy the city immediately (one-city challenge only)
        - liberate: Return the city to its original owner (requires liberate_to)
        """
        city_id = self._require_param(args, "city_id", int)
        action = self._require_param(args, "action", str)

        valid_actions = ["puppet", "annex", "raze", "destroy", "liberate"]
        if action not in valid_actions:
            raise ToolError(f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}")
        if action == "liberate" and args.get("liberate_to") is None:
            raise ToolError("liberate_to is required when action is 'liberate'")

        pipe = self._get_pipe()
        message: dict[str, Any] = {
            "type": "city_capture_decision",
            "city_id": city_id,
            "action": action,
        }
        for key in ("liberate_to", "player_id"):
            if args.get(key) is not None:
                message[key] = args[key]

        try:
            return pipe.send_request(message, timeout=10.0)
        except Exception as e:
            return {"status": "error", "error": f"Failed to make city decision: {e}"}

    def _set_city_production(self, args: dict[str, Any]) -> dict[str, Any]:
        """Set production for a city.

        Use this when the game shows a 'choose_production' popup. The available
        items and their IDs are sent via the popup_choice_needed message.

        Order types:
        - 0 = ORDER_TRAIN (units)
        - 1 = ORDER_CONSTRUCT (buildings)
        - 2 = ORDER_CREATE (projects/wonders)
        - 3 = ORDER_MAINTAIN (processes like Wealth, Research, etc.)
        """
        city_id = self._require_param(args, "city_id", int)
        order_type = self._require_param(args, "order_type", int)
        item_id = self._require_param(args, "item_id", int)

        if order_type not in [0, 1, 2, 3]:
            raise ToolError(f"Invalid order_type {order_type}. Must be 0-3.")

        pipe = self._get_pipe()
        message: dict[str, Any] = {
            "type": "set_city_production",
            "city_id": city_id,
            "order_type": order_type,
            "item_id": item_id,
        }
        if args.get("player_id") is not None:
            message["player_id"] = args["player_id"]

        try:
            return pipe.send_request(message, timeout=10.0)
        except Exception as e:
            return {"status": "error", "error": f"Failed to set city production: {e}"}

    def _choose_tech(self, args: dict[str, Any]) -> dict[str, Any]:
        """Select a technology to research.

        Use this when the game shows a 'choose_tech' popup. The available
        technologies and their IDs are sent via the popup_choice_needed message.
        """
        tech_id = self._require_param(args, "tech_id", int)

        pipe = self._get_pipe()
        message: dict[str, Any] = {"type": "choose_tech", "tech_id": tech_id}
        if args.get("player_id") is not None:
            message["player_id"] = args["player_id"]

        try:
            return pipe.send_request(message, timeout=10.0)
        except Exception as e:
            return {"status": "error", "error": f"Failed to choose tech: {e}"}

    # -------------------------------------------------------------------------
    # DLL Query Tools
    # -------------------------------------------------------------------------

    def _get_game_state(self, args: dict[str, Any]) -> dict[str, Any]:
        """Query the DLL for current game state."""
        return self._send_pipe_request("get_state")

    def _get_current_turn(self, args: dict[str, Any]) -> dict[str, Any]:
        """Query the DLL for the current turn number."""
        return self._send_pipe_request("get_state")

    def _get_cities(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get information about cities from DLL."""
        return self._send_pipe_request("get_cities")

    def _get_city_production(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get available production options for a specific city."""
        city_id = self._require_param(args, "city_id", int)
        return self._send_pipe_request("get_city_production", city_id=city_id)

    def _get_units(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get information about units from DLL."""
        return self._send_pipe_request("get_units")

    def _get_notifications(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get notifications from the log (filtered by current game)."""
        game_id = self.current_game_id
        notifications = self._message_logger.get_messages(
            message_type="notification", game_id=game_id
        )
        return {
            "notifications": notifications,
            "count": len(notifications),
            "game_id": game_id,
            "session_id": self.current_session_id,
            "player_id": self.current_player_id,
        }

    def _get_log(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get log entries from the JSONL log with optional filters."""
        message_type = args.get("message_type")
        direction = args.get("direction")
        turn_number = args.get("turn_number")
        player_id = args.get("player_id")
        game_id = args.get("game_id")
        session_id = args.get("session_id")
        current_game_only = args.get("current_game_only", True)
        limit = min(args.get("limit", 100), 1000)

        # Default to current game if not specified
        if current_game_only and game_id is None:
            game_id = self.current_game_id

        # Special handling for 'note' type - notes are tool_call entries with tool="add_note"
        if message_type == "note":
            all_messages = self._message_logger.get_messages(
                message_type="tool_call",
                turn_number=turn_number,
                player_id=player_id,
                game_id=game_id,
                session_id=session_id,
            )
            messages = [m for m in all_messages if m.get("tool") == "add_note"]
        else:
            messages = self._message_logger.get_messages(
                message_type=message_type,
                turn_number=turn_number,
                player_id=player_id,
                game_id=game_id,
                session_id=session_id,
            )

        if direction:
            messages = [m for m in messages if m.get("direction") == direction]

        # Filter out deleted messages (those with a 'deleted' timestamp)
        messages = [m for m in messages if "deleted" not in m]

        # Most recent first, limited
        messages = list(reversed(messages))[:limit]

        return {
            "messages": messages,
            "count": len(messages),
            "game_id": game_id,
            "session_id": self.current_session_id,
        }

    def _ping(self, args: dict[str, Any]) -> dict[str, Any]:
        """Ping the DLL to check connectivity and get server status."""
        result = self._send_pipe_request("ping")

        # Add orchestrator stats to the result
        with self._lock:
            result["orchestrator_stats"] = {
                "turn_number": self._current_turn_number,
                "action_count": self._action_count,
                "action_errors": self._action_errors,
            }

        return result

    def _add_note(self, args: dict[str, Any]) -> dict[str, Any]:
        """Add a note. Content is captured in the tool_call log entry."""
        content = self._require_param(args, "content", str)
        return {"status": "success", "content_length": len(content)}

    def _delete_note(self, args: dict[str, Any]) -> dict[str, Any]:
        """Mark a note as deleted by setting a 'deleted' timestamp on it."""
        note_id = self._require_param(args, "note_id", str)
        found = self._message_logger.mark_deleted(note_id)
        if found:
            return {"status": "success", "note_id": note_id}
        else:
            return {"status": "error", "error": f"Note not found: {note_id}"}
    
