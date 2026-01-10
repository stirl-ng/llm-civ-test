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
import uuid
from typing import TYPE_CHECKING, Any, Optional


if TYPE_CHECKING:
    from .pipe_server import PipeConnection, StateProcessor



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
        self._end_turn_in_progress = False
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
            "end_turn_in_progress": self._end_turn_in_progress,
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

    def start_turn(self, state: dict[str, Any], pipe_conn: "PipeConnection") -> None:
        """Update turn state with the given game state and pipe connection.

        Args:
            state: Game state from DLL (contains turn, player_id, game_id, session_id)
            pipe_conn: PipeConnection for sending actions to DLL
        """
        new_turn_num = state.get("turn")
        new_game_id = state.get("game_id")
        new_session_id = state.get("session_id")
        new_player_id = state.get("player_id")

        with self._lock:
            # Update all state
            self._pipe_conn = pipe_conn
            self._current_turn_number = new_turn_num
            self._current_game_id = new_game_id
            self._current_session_id = new_session_id
            self._current_player_id = new_player_id
            self._end_turn_in_progress = False

            # Reset action statistics for new turn
            self._action_count = 0
            self._action_errors = 0
            self._last_action_time = None
    
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

    def _send_pipe_request(
        self, request_type: str, timeout: float = 5.0, request_id: Optional[str] = None, **extra_fields: Any
    ) -> dict[str, Any]:
        """Send a request to the DLL and return the response.

        Args:
            request_type: The message type (e.g., "get_state", "get_units")
            timeout: Request timeout in seconds
            request_id: Request ID for request/response matching (required for proper matching)
            **extra_fields: Additional fields to include in the request

        Returns:
            Response dict from DLL

        Raises:
            ToolError: If no pipe connection or request fails
        """
        pipe = self._get_pipe()
        # uuid should always be provided by execute_tool, but generate one if missing for safety
        if request_id is None:
            request_id = str(uuid.uuid4())
        request = {
            "type": request_type,
            "request_id": request_id,
            **extra_fields,
        }
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
        
        Generates a request_id for all tools that need to match request/response.
        """
        # Generate request_id for DLL-calling tools
        request_id = str(uuid.uuid4())
        
        # Execute the tool
        try:
            if name in self._TOOLS:
                handler_name, _ = self._TOOLS[name]
                handler = getattr(self, handler_name)
                result = handler(request_id, arguments)
                
                # Verify request_id matching for DLL-calling tools
                response_request_id = result.get("request_id")
                if response_request_id != request_id:
                    raise ToolError(f"Request ID mismatch for tool '{name}': sent {request_id}, received {response_request_id}")

            elif name in self._PLACEHOLDER_TOOLS:
                result = self._not_implemented(name)

            else:
                raise ToolError(f"Unknown tool: {name}")
        except ToolError as e:
            result = {"error": str(e), "status": "error"}
        except Exception as e:
            result = {"error": str(e), "status": "error"}

        # Single log entry with both call and result
        self._message_logger.log_message({
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
        "delete_message": ("_delete_message", {"message_id": "required string (uuid of message to delete)"}),
        "delete_note": ("_delete_message", {"message_id": "required string (uuid of note to delete)"}),
        # Action tools
        "send_action": ("_send_action", {"action": "required dict with 'kind' field"}),
        "end_turn": ("_end_turn", {"turn": "required int"}),
    }

    # Placeholder tools - description only, not yet implemented in DLL
    _PLACEHOLDER_TOOLS: dict[str, str] = {
        "get_tech_tree": "Get technology tree status.",
        "get_diplomacy": "Get diplomatic status with all known civilizations.",
        "get_available_choices": "Get all pending decisions (tech, policy, production, etc.)",
        "get_victory_progress": "Get progress toward all victory conditions.",
        "get_resources": "Get strategic and luxury resources.",
        "get_state_refresh": "Force a full state refresh from the DLL.",
        "get_player_status": "Get detailed status information for a player.",
    }

    def _send_action(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Send an action to the DLL and return the response.
        
        Args:
            request_id: Request ID to use for request/response matching
            args: Tool arguments containing the action
        """
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

        # Convert action to message: 'kind' -> 'type', use provided request_id
        message = {k: v for k, v in action.items() if k != "kind"}
        message["type"] = action_kind
        message["request_id"] = request_id

        # Send and track stats
        try:
            result = pipe.send_action(message, timeout=10.0)
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

    def _end_turn(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Signal that the LLM is done with its turn and wait for DLL confirmation.

        The DLL might block the end-turn request if there are pending units,
        tech choices, etc. This method waits for the authoritative result.
        
        Args:
            request_id: Request ID to use for request/response matching
            args: Tool arguments containing the turn number
        """
        turn = self._require_param(args, "turn", int)
        with self._lock:
            if self._end_turn_in_progress:
                return {"error": "An end_turn request is already in progress", "status": "error"}
            # Mark that we're processing an end_turn to prevent concurrent calls
            self._end_turn_in_progress = True
            pipe_conn = self._pipe_conn
            current_turn = self._current_turn_number

        if not pipe_conn:
            with self._lock:
                self._end_turn_in_progress = False
            return {"error": "No pipe connection available", "status": "error"}

        # Validate that we have a current turn number set
        if current_turn is None:
            with self._lock:
                self._end_turn_in_progress = False
            return {
                "error": "No active turn - turn_start has not been received yet",
                "status": "error",
                "requested_turn": turn,
                "current_turn": None,
                "message": "Cannot end turn: no turn has been started. Wait for turn_start message from DLL."
            }

        # Validate turn matches current turn
        if turn != current_turn:
            with self._lock:
                self._end_turn_in_progress = False
            return {
                "error": f"Turn mismatch: requested turn {turn} but current turn is {current_turn}",
                "status": "error",
                "requested_turn": turn,
                "current_turn": current_turn,
                "message": f"Turn number mismatch. You requested to end turn {turn}, but the current turn is {current_turn}."
            }

        # Send end_turn to DLL and wait for end_turn_result
        try:
            result = pipe_conn.send_end_turn(turn=turn, request_id=request_id, timeout=15.0)
            
            status = result.get("status", "unknown")
            
            if status == "success":
                with self._lock:
                    self._end_turn_in_progress = False
                return {
                    "status": "success",
                    "turn": turn,
                    "message": "Turn ended successfully"
                }

            elif status == "blocked":
                blocker = result.get("blocker", "unknown")
                with self._lock:
                    self._end_turn_in_progress = False
                return {
                    "status": "blocked",
                    "blocker": blocker,
                    "message": f"Turn cannot end yet: {blocker}. Please resolve the blocker and try again."
                }

            elif status == "already_ended":
                with self._lock:
                    self._end_turn_in_progress = False
                return {
                    "status": "already_ended",
                    "message": "Turn has already been ended"
                }

            elif status == "timeout":
                with self._lock:
                    self._end_turn_in_progress = False
                return {
                    "status": "timeout",
                    "error": "DLL did not respond to end_turn request in time"
                }

            else:
                with self._lock:
                    self._end_turn_in_progress = False
                return {
                    "status": "error",
                    "error": f"DLL returned unexpected status: {status}",
                    "result": result
                }

        except Exception as e:
            with self._lock:
                self._end_turn_in_progress = False
            return {"error": f"Failed to end turn: {e}"}

    # -------------------------------------------------------------------------
    # DLL Query Tools
    # -------------------------------------------------------------------------

    def _get_game_state(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Query the DLL for current game state."""
        # category = args.get("category")  # Reserved for future use
        result = self._send_pipe_request("get_state", request_id=request_id)
        if result.get("type") == "state_refresh":
            state = result.get("state", {})
            return {
                "status": "success",
                "turn": state.get("turn"),
                "active_player": state.get("activePlayer"),
                "state": state,
            }
        return result

    def _get_current_turn(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Query the DLL for the current turn number."""
        result = self._send_pipe_request("get_state", request_id=request_id)
        if result.get("type") == "state_refresh":
            state = result.get("state", {})
            return {
                "status": "success",
                "turn": state.get("turn"),
                "active_player": state.get("activePlayer"),
            }
        return result

    def _get_cities(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Get information about cities from DLL."""
        # city_id = args.get("city_id")  # Reserved for future filtering
        return self._send_pipe_request("get_cities", request_id=request_id)

    def _get_units(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Get information about units from DLL."""
        # player_id = args.get("player_id")  # Reserved for future filtering
        return self._send_pipe_request("get_units", request_id=request_id)

    def _get_notifications(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
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
            "request_id": request_id,
        }
    
    def _get_log(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Get log entries from the JSONL log with optional filters.

        Args:
            request_id: Request ID for this tool call (used in response)
            args: Tool arguments containing optional filters:
                - message_type: Filter by type (e.g., 'note', 'turn_start')
                - direction: Filter by 'incoming' or 'outgoing'
                - turn_number: Minimum turn number
                - player_id, game_id, session_id: ID filters
                - current_game_only: If True, filter to current game (default True)
                - limit: Max messages to return (default 100, max 1000)

        Returns:
            Dictionary with 'messages' list and 'count'
        """
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

        # Build set of deleted message UUIDs by scanning delete_message tool calls
        all_tool_calls = self._message_logger.get_messages(
            message_type="tool_call", game_id=game_id, session_id=session_id
        )
        deleted_uuids = set()
        for tc in all_tool_calls: # TODO not how deleted logic works (deleted timestamp)
            tool = tc.get("tool")
            if tool in ("delete_message", "delete_note"):
                deleted_id = tc.get("arguments", {}).get("message_id")
                if deleted_id:
                    deleted_uuids.add(deleted_id)

        # Filter out deleted messages
        messages = [m for m in messages if m.get("uuid") not in deleted_uuids]

        # Most recent first, limited
        messages = list(reversed(messages))[:limit]

        return {
            "messages": messages,
            "count": len(messages),
            "game_id": game_id,
            "session_id": self.current_session_id,
            "request_id": request_id,
        }
    
    def _ping(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Ping the DLL to check connectivity and get server status."""
        result = self._send_pipe_request("ping", request_id=request_id)

        with self._lock:
            stats = {
                "turn_number": self._current_turn_number,
                "action_count": self._action_count,
                "action_errors": self._action_errors,
            }

        if result.get("type") == "pong":
            return {
                "status": "ok",
                "server": "civ5-mcp",
                "dll_response": "pong",
                "timestamp": time.time(),
                **stats,
            }
        return {"status": "error", "error": result.get("error", "Unexpected response")}
    
    def _add_note(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Add a note. Content is captured in the tool_call log entry."""
        content = self._require_param(args, "content", str)
        return {
            "status": "success",
            "content_length": len(content),
            "request_id": request_id,
        }

    def _delete_message(self, request_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Mark a message (or note) as deleted by its uuid. Deletion is recorded in the tool_call log."""
        message_id = self._require_param(args, "message_id", str)
        return {
            "status": "success",
            "message_id": message_id,
            "request_id": request_id,
        }
    
