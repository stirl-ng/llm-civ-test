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
from typing import TYPE_CHECKING, Any, Callable, Optional


if TYPE_CHECKING:
    from .game_state import GameState



class ToolError(Exception):
    """Raised when a tool encounters an error (param validation, missing pipe, etc.)."""
    pass


class CivMCPServer:
    """Tool executor that bridges LLM requests to Civ V game.

    Sequential turn flow:
    1. Orchestrator calls start_turn(state) when DLL sends turn_start
    2. LLM queries state and sends actions via tools (all queries go to DLL)
    3. Each action is sent immediately to DLL via send_request callback, response returned to LLM
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

    def __init__(
        self, 
        send_request: Optional[Callable[[dict[str, Any], float], dict[str, Any]]] = None,
        game_state: Optional["GameState"] = None
    ):
        """Initialize the MCP server.

        Args:
            send_request: Callback to send requests to DLL: (request, timeout) -> response
            game_state: GameState instance to read metadata from (single source of truth)
        """
        self._send_request = send_request
        self.game_state = game_state
        self._lock = threading.Lock()

        self.uptime = time.monotonic()

        # Message logger (JSONL file) - singleton, shared across all components
        from .message_logger import get_message_logger
        self._message_logger = get_message_logger()

    def get_about(self) -> dict[str, Any]:
        """Get information about the MCP server."""
        with self._lock:
            return {
                "current_turn_number": self.turn_number,
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

    @property
    def turn_number(self) -> Optional[int]:
        """Get the current turn number."""
        if self.game_state:
            return self.game_state.turn_number
        return None

    @property
    def current_game_id(self) -> Optional[int]:
        """Get the current game ID (persists across saves)."""
        if self.game_state:
            return self.game_state.game_id
        return None

    @property
    def current_session_id(self) -> Optional[int]:
        """Get the current session ID (changes per pipe connection)."""
        if self.game_state:
            return self.game_state.session_id
        return None

    @property
    def current_player_id(self) -> Optional[int]:
        """Get the current player ID."""
        if self.game_state:
            return self.game_state.player_id
        return None

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

    def _condition_request(self, request: dict[str, Any]) -> None:
        """Add context fields to a request dict if they're not already present.
        
        Modifies the request dict in-place.
        
        Args:
            request: Request dictionary to condition
        """
        with self._lock:
            if "game_id" not in request:
                request["game_id"] = self.current_game_id
            if "session_id" not in request:
                request["session_id"] = self.current_session_id
            if "player_id" not in request:
                request["player_id"] = self.current_player_id
            if "turn" not in request:
                request["turn"] = self.turn_number

    def _send_pipe_request(
        self, 
        request_type: str | None = None,
        request: dict[str, Any] | None = None,
        timeout: float = 5.0, 
        **extra_fields: Any
    ) -> dict[str, Any]:
        """Send a request to the DLL and return the response.

        Can be called in two ways:
        1. With request_type string: _send_pipe_request("get_state", timeout=5.0, city_id=123)
        2. With pre-built request dict: _send_pipe_request(request={"type": "select_pantheon", "belief_id": 5, timeout=5.0})

        Args:
            request_type: The message type (e.g., "get_state", "get_units"). Mutually exclusive with request.
            request: Pre-built request dictionary. Mutually exclusive with request_type.
            timeout: Request timeout in seconds
            **extra_fields: Additional fields to include in the request (only used with request_type)

        Returns:
            Response dict from DLL

        Raises:
            ToolError: If no send_request callback configured, both/neither args provided, or request fails
        """
        if not self._send_request:
            raise ToolError("No send_request callback configured")
        
        if request_type is not None and request is not None:
            raise ToolError("Cannot provide both request_type and request")
        if request_type is None and request is None:
            raise ToolError("Must provide either request_type or request")
        
        # Build request dict
        if request_type is not None:
            request = {"type": request_type, **extra_fields}
        else:
            # Use provided request, but allow extra_fields to override/extend
            request = {**request, **extra_fields}
        
        self._condition_request(request)
        
        try:
            return self._send_request(request, timeout)
        except Exception as e:
            raise ToolError(f"Request failed: {e}") from e


    def _get_tools(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get the list of available tools with their descriptions and parameters."""
        tools = self.get_tools()
        return {
            "status": "success",
            "tools": tools,
            "count": len(tools)
        }

    def _not_implemented(self, tool_name: str) -> dict[str, Any]:
        """Return a standard 'not implemented' response for placeholder tools."""
        return {
            "status": "not_implemented",
            "message": f"Tool '{tool_name}' is not yet implemented in the DLL",
        }

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return results.

        Tool request is logged separately in mcp_http_server.py.
        Tool response is logged here after execution.
        ToolErrors are expected (validation failures) and returned cleanly.
        """
        # Some tools don't require send_request (local tools)
        local_tools = {"get_tools", "ping"}
        requires_send_request = name in self._TOOLS and name not in local_tools

        if requires_send_request and not self._send_request:
            return {"error": "No send_request callback configured", "status": "error"}

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

        # Log tool response (incoming to LLM from orchestrator)
        # Include arguments so dashboard can display them in modal
        self._message_logger.log({
            "type": "tool_response",
            "tool": name,
            "arguments": arguments,
            "result": result,
        }, direction="incoming")

        return result

    # -------------------------------------------------------------------------
    # Tool Registry
    # -------------------------------------------------------------------------
    # Each tool maps to (handler_method_name, params_dict)
    # Description comes from the handler's docstring

    _TOOLS: dict[str, tuple[str, dict]] = {
        # Meta tools (local)
        "get_tools": ("_get_tools", {}),
        "ping": ("_ping", {}),
        # Query tools (DLL requests)
        "get_game_state": ("_get_game_state", {"category": "optional string"}),
        "get_current_turn": ("_get_current_turn", {}),
        "get_cities": ("_get_cities", {"city_id": "optional int"}),
        "get_city_production": ("_get_city_production", {"city_id": "required int"}),
        "get_units": ("_get_units", {"player_id": "optional int"}),
        "get_notifications": ("_get_notifications", {}),
        "get_turn_blockers": ("_get_turn_blockers", {"player_id": "optional int"}),
        "get_available_techs": ("_get_available_techs", {"player_id": "optional int"}),
        "get_available_policies": ("_get_available_policies", {"player_id": "optional int"}),
        "adopt_policy": ("_adopt_policy", {
            "policy_id": "optional int - ID of policy to adopt (use this OR branch_id)",
            "branch_id": "optional int - ID of branch to unlock (use this OR policy_id)",
            "player_id": "optional int - player ID (defaults to active player)"
        }),
        # Log tools (local)
        "get_log": ("_get_log", {
            "message_type": "optional string (e.g., 'turn_start', 'notification')",
            "direction": "optional string: 'incoming'|'outgoing'",
            "turn_number": "optional int",
            "player_id": "optional int",
            "game_id": "optional int (overrides current_game_only)",
            "session_id": "optional int",
            "current_game_only": "optional bool (default True)",
            "limit": "optional int (default 100, max 1000)",
        }),
        # Action tools
        "send_action": ("_send_action", {"action": "required dict with 'kind' field"}),
        "end_turn": ("_end_turn", {"turn": "required int"}),
        "force_end_turn": ("_force_end_turn", {"turn": "required int"}),
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
        # Spatial awareness tools
        "get_visible_tiles": ("_get_visible_tiles", {}),
        "get_map_view": ("_get_map_view", {
            "center": "optional string - 'capital', 'unit:<id>', or '<x>,<y>' (default: 'capital')",
            "radius": "optional int - tiles from center to edge (default: 10)",
            "layers": "optional list[string] - which layers to show: terrain, resources, improvements, units, cities",
            "show_legend": "optional bool - include symbol legend (default: true)"
        }),
        "get_unit_build_options": ("_get_unit_build_options", {
            "unit_id": "required int - ID of the worker/builder unit",
            "radius": "optional int - search radius from unit (default: 5)",
            "include_all_tiles": "optional bool - include tiles with no valid builds (default: false)"
        }),
        "get_reachable_tiles": ("_get_reachable_tiles", {
            "unit_id": "required int - ID of the unit",
            "include_attacks": "optional bool - include attackable tiles (default: true)"
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
            raise ToolError("Action cannot be empty")
        if "kind" not in action:
            raise ToolError("Action missing required 'kind' field")

        action_kind = action["kind"]

        # Convert action to message: 'kind' -> 'type'
        message = {k: v for k, v in action.items() if k != "kind"}
        message["type"] = action_kind

        # Send to DLL
        return self._send_pipe_request(request=message)

    def _end_turn(self, args: dict[str, Any]) -> dict[str, Any]:
        """Signal that the LLM is done with its turn and wait for DLL confirmation.

        The DLL might block the end-turn request if there are pending units,
        tech choices, etc. This method waits for the authoritative result.
        """
        turn = self._require_param(args, "turn", int)
        with self._lock:
            current_turn = self.turn_number

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
            return self._send_pipe_request(request={"type": "end_turn", "turn": turn})
        except ToolError as e:
            return {"status": "error", "error": str(e)}

    def _force_end_turn(self, args: dict[str, Any]) -> dict[str, Any]:
        """Force end the turn by calling doControl(CONTROL_ENDTURN), bypassing normal checks.

        Use this when end_turn fails due to blockers that cannot be resolved (e.g., stuck UI).
        This directly triggers the game's end-turn control without validation.
        """
        turn = self._require_param(args, "turn", int)
        with self._lock:
            current_turn = self.turn_number

        # Validate that we have a current turn number set
        if current_turn is None:
            return {
                "error": "No active turn - turn_start has not been received yet",
                "status": "error",
                "requested_turn": turn,
                "current_turn": None,
                "message": "Cannot force end turn: no turn has been started. Wait for turn_start message from DLL."
            }

        # Validate turn matches current turn
        if turn != current_turn:
            return {
                "error": f"Turn mismatch: requested turn {turn} but current turn is {current_turn}",
                "status": "error",
                "requested_turn": turn,
                "current_turn": current_turn,
                "message": f"Turn number mismatch. You requested to force end turn {turn}, but the current turn is {current_turn}."
            }

        try:
            return self._send_pipe_request(request={"type": "force_end_turn", "turn": turn})
        except ToolError as e:
            return {"status": "error", "error": str(e)}

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

        message = {"type": "select_pantheon", "belief_id": belief_id}
        if player_id is not None:
            message["player_id"] = player_id

        return self._send_pipe_request(request=message)

    def _found_religion(self, args: dict[str, Any]) -> dict[str, Any]:
        """Found a new religion for the player.

        Use this when the game shows a 'found_religion' popup. The available
        religions and beliefs are sent via the popup_choice_needed message.
        """
        religion_id = self._require_param(args, "religion_id", int)
        founder_belief_id = self._require_param(args, "founder_belief_id", int)
        follower_belief_id = self._require_param(args, "follower_belief_id", int)

        message: dict[str, Any] = {
            "type": "found_religion",
            "religion_id": religion_id,
            "founder_belief_id": founder_belief_id,
            "follower_belief_id": follower_belief_id,
        }
        for key in ("pantheon_belief_id", "bonus_belief_id", "religion_name", "city_x", "city_y", "player_id"):
            if args.get(key) is not None:
                message[key] = args[key]

        return self._send_pipe_request(request=message)

    def _enhance_religion(self, args: dict[str, Any]) -> dict[str, Any]:
        """Enhance an existing religion with additional beliefs.

        Use this when the game shows an 'enhance_religion' popup. The available
        beliefs are sent via the popup_choice_needed message.
        """
        follower2_belief_id = self._require_param(args, "follower2_belief_id", int)
        enhancer_belief_id = self._require_param(args, "enhancer_belief_id", int)

        message: dict[str, Any] = {
            "type": "enhance_religion",
            "follower2_belief_id": follower2_belief_id,
            "enhancer_belief_id": enhancer_belief_id,
        }
        if args.get("player_id") is not None:
            message["player_id"] = args["player_id"]

        return self._send_pipe_request(request=message)

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

        message: dict[str, Any] = {
            "type": "city_capture_decision",
            "city_id": city_id,
            "action": action,
        }
        for key in ("liberate_to", "player_id"):
            if args.get(key) is not None:
                message[key] = args[key]

        return self._send_pipe_request(request=message)

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

        message: dict[str, Any] = {
            "type": "set_city_production",
            "city_id": city_id,
            "order_type": order_type,
            "item_id": item_id,
        }
        if args.get("player_id") is not None:
            message["player_id"] = args["player_id"]

        return self._send_pipe_request(request=message)

    def _choose_tech(self, args: dict[str, Any]) -> dict[str, Any]:
        """Select a technology to research.

        Use this when the game shows a 'choose_tech' popup. The available
        technologies and their IDs are sent via the popup_choice_needed message.
        """
        tech_id = self._require_param(args, "tech_id", int)

        message: dict[str, Any] = {"type": "choose_tech", "tech_id": tech_id}
        if args.get("player_id") is not None:
            message["player_id"] = args["player_id"]

        return self._send_pipe_request(request=message)

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
        notifications = self._message_logger.query(
            message_type="notification", game_id=game_id
        )
        return {
            "notifications": notifications,
            "count": len(notifications),
            "game_id": game_id,
            "session_id": self.current_session_id,
            "player_id": self.current_player_id,
        }

    def _get_turn_blockers(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get all current end-turn blockers (units needing orders, choices, etc.)."""
        player_id = args.get("player_id")
        if player_id is not None:
            return self._send_pipe_request("get_turn_blockers", player_id=player_id)
        return self._send_pipe_request("get_turn_blockers")

    def _get_available_techs(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get available technologies for research from DLL."""
        player_id = args.get("player_id")
        if player_id is not None:
            return self._send_pipe_request("get_available_techs", player_id=player_id)
        return self._send_pipe_request("get_available_techs")

    def _get_available_policies(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get available policy branches and policies from DLL."""
        player_id = args.get("player_id")
        if player_id is not None:
            return self._send_pipe_request("get_available_policies", player_id=player_id)
        return self._send_pipe_request("get_available_policies")

    def _adopt_policy(self, args: dict[str, Any]) -> dict[str, Any]:
        """Adopt a policy or unlock a policy branch."""
        policy_id = args.get("policy_id")
        branch_id = args.get("branch_id")
        player_id = args.get("player_id")

        if policy_id is None and branch_id is None:
            raise ToolError("Must provide either policy_id or branch_id")

        kwargs: dict[str, Any] = {}
        if policy_id is not None:
            kwargs["policy_id"] = policy_id
        if branch_id is not None:
            kwargs["branch_id"] = branch_id
        if player_id is not None:
            kwargs["player_id"] = player_id

        return self._send_pipe_request("adopt_policy", **kwargs)

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

        messages = self._message_logger.query(
            message_type=message_type,
            direction=direction,
            turn=turn_number,
            player_id=player_id,
            game_id=game_id,
            session_id=session_id,
            limit=limit,
        )

        return {
            "messages": messages,
            "count": len(messages),
            "game_id": game_id,
            "session_id": self.current_session_id,
        }

    def _ping(self, args: dict[str, Any]) -> dict[str, Any]:
        """Ping the DLL to check connectivity and get server status."""
        return self._send_pipe_request("ping")

    def _get_visible_tiles(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get raw tile data for all revealed tiles - use get_map_view instead for visual overview."""
        return self._send_pipe_request("get_visible_tiles")

    def _get_map_view(self, args: dict[str, Any]) -> dict[str, Any]:
        """ESSENTIAL: Get ASCII map showing terrain, units, cities, resources around a location. Use this to understand the world before moving units or making decisions."""
        from .map_renderer import render_map_with_context

        # Get optional parameters
        center_str = args.get("center", "capital")
        radius = args.get("radius", 10)
        layers = args.get("layers")
        show_legend = args.get("show_legend", True)

        # Get tiles from DLL
        tiles_response = self._send_pipe_request("get_visible_tiles")
        if not tiles_response.get("success", True):
            return tiles_response

        tiles = tiles_response.get("tiles", [])
        turn = tiles_response.get("turn")

        # Get units and cities for overlay
        units_response = self._send_pipe_request("get_units")
        units = units_response.get("units", []) if units_response.get("success", True) else []

        cities_response = self._send_pipe_request("get_cities")
        cities = cities_response.get("cities", []) if cities_response.get("success", True) else []

        # Mark all cities as ours (get_cities only returns player's own cities)
        for city in cities:
            city["is_ours"] = True

        # Parse center parameter
        center = None
        center_name = None

        if center_str == "capital":
            # Find capital city
            for city in cities:
                if city.get("is_capital"):
                    center = (city["x"], city["y"])
                    center_name = city.get("name", "Capital")
                    break
        elif center_str.startswith("unit:"):
            # Center on unit
            try:
                unit_id = int(center_str[5:])
                for unit in units:
                    if unit["id"] == unit_id:
                        center = (unit["x"], unit["y"])
                        center_name = f"{unit.get('unit_type_name', 'Unit')} #{unit_id}"
                        break
            except ValueError:
                pass
        elif "," in center_str:
            # Parse as coordinates
            try:
                parts = center_str.split(",")
                x, y = int(parts[0]), int(parts[1])
                center = (x, y)
            except (ValueError, IndexError):
                pass

        # Filter units and cities to viewport if center specified
        viewport_units = []
        viewport_cities = []
        if center:
            for unit in units:
                if abs(unit["x"] - center[0]) <= radius and abs(unit["y"] - center[1]) <= radius:
                    viewport_units.append(unit)
            for city in cities:
                if abs(city["x"] - center[0]) <= radius and abs(city["y"] - center[1]) <= radius:
                    viewport_cities.append(city)
        else:
            viewport_units = units
            viewport_cities = cities

        # Render map
        map_str = render_map_with_context(
            tiles=tiles,
            units=viewport_units,
            cities=viewport_cities,
            center=center,
            radius=radius,
            layers=layers,
            show_legend=show_legend,
            turn=turn,
            center_name=center_name
        )

        return {
            "success": True,
            "map": map_str,
            "center": center,
            "radius": radius,
            "turn": turn,
            "num_tiles": len(tiles),
            "num_units": len(viewport_units),
            "num_cities": len(viewport_cities)
        }

    def _get_unit_build_options(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get what a Worker can build (farms, mines, roads, etc.) on nearby tiles. Use before issuing build commands."""
        unit_id = self._require_param(args, "unit_id", int)
        radius = args.get("radius", 5)
        include_all_tiles = args.get("include_all_tiles", False)

        return self._send_pipe_request(
            "get_unit_build_options",
            unit_id=unit_id,
            radius=radius,
            include_all_tiles=include_all_tiles
        )

    def _get_reachable_tiles(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get all tiles a unit can move to THIS turn, including attackable enemies. Use to plan tactical movement."""
        unit_id = self._require_param(args, "unit_id", int)
        include_attacks = args.get("include_attacks", True)

        return self._send_pipe_request(
            "get_reachable_tiles",
            unit_id=unit_id,
            include_attacks=include_attacks
        )

