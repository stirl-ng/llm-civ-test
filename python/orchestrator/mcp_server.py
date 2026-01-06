"""
MCP Server for Civilization V LLM Orchestrator

Provides tools for LLMs to:
- Query game state (via DLL requests)
- Send actions immediately to the DLL (synchronous, with response)
- End their turn when done deciding

Each action is sent immediately to the DLL and the response is returned
to the LLM, allowing it to see the result before deciding the next action.
"""

import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any, Optional


if TYPE_CHECKING:
    from .pipe_server import PipeConnection

logger = logging.getLogger(__name__)


def _validate_action(action: Any) -> tuple[bool, Optional[str]]:
    """Validate that an action is properly formatted.
    
    Args:
        action: The action to validate (should have 'kind' field)
        
    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    if not isinstance(action, dict):
        return False, f"Action must be a dictionary, got {type(action).__name__}"
    
    if not action:
        return False, "Action cannot be empty"
    
    # Check for required 'kind' field (will become message 'type')
    if "kind" not in action:
        return False, "Action missing required 'kind' field"
    
    return True, None


# Tool definitions for documentation/discovery
AVAILABLE_TOOLS = [
    {
        "name": "get_game_state",
        "description": "Get the current game state. Optionally filter by category.",
        "parameters": {"category": "optional string"},
    },
    {
        "name": "send_action",
        "description": "Send an action to the game (fire-and-forget, non-blocking). Does not wait for response.",
        "parameters": ["action"],
    },
    {
        "name": "get_cities",
        "description": "Get detailed information about all cities.",
        "parameters": {"city_id": "optional int"},
    },
    {
        "name": "get_units",
        "description": "Get information about all units.",
        "parameters": {"player_id": "optional int (defaults to active player)"},
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
        "name": "get_state_refresh",
        "description": "Force a full state refresh from the DLL.",
        "parameters": {},
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
        "description": "Mark a notification as acknowledged by its lookup_index (use the lookup_index field from get_notifications).",
        "parameters": ["notification_id"],
    },
    {
        "name": "get_player_status",
        "description": "Get detailed status information for a player (science, gold, happiness, etc.).",
        "parameters": {"player_id": "optional int (defaults to active player)"},
    },
    {
        "name": "send_action_with_confirmation",
        "description": "Send an action and then query the game state after a delay to confirm it executed. Useful for moves where you want to verify the unit moved.",
        "parameters": {"action": "action dict", "delay_seconds": "optional float (default 0.5)", "query_type": "optional string: 'units'|'state' (default 'units')"},
    },
    {
        "name": "ping",
        "description": "Ping the server to check connectivity and get server status.",
        "parameters": {},
    },
]


class CivMCPServer:
    """Tool executor that bridges LLM requests to Civ V game.

    Sequential turn flow:
    1. Orchestrator calls start_turn(state, pipe_connection)
    2. LLM queries state and sends actions via tools (all queries go to DLL)
    3. Each action is sent immediately to DLL, response returned to LLM
    4. LLM calls end_turn when done
    5. Orchestrator resumes, signals DLL to advance turn
    """

    def __init__(
        self,
        turn_timeout: float = 300.0
    ):
        """Initialize the MCP server.

        Args:
            turn_timeout: Max seconds to wait for LLM to end turn (default 5 min)
        """
        self.turn_timeout = turn_timeout

        # Pipe connection for sending actions (set during turn)
        self._pipe_conn: Optional["PipeConnection"] = None

        # Turn management
        self._turn_active = False
        self._turn_ended = threading.Event()
        self._turn_notes: str = ""
        self._current_turn_number: Optional[int] = None  # Track which turn is active
        self._first_turn_of_game: Optional[int] = None  # Track first turn of current game session
        self._lock = threading.Lock()
        
        # Action statistics
        self._action_count = 0
        self._action_errors = 0
        self._last_action_time: Optional[float] = None
        
        # Game logger (JSONL file) - logs everything from DLL
        from .game_logger import GameLogger
        self._message_logger = GameLogger()

    def start_turn(self, state: dict[str, Any], pipe_conn: "PipeConnection") -> None:
        """Start a new turn with the given game state and pipe connection.

        If a turn is already active, it will be cancelled (e.g., user manually advanced turn).

        Args:
            state: Game state from DLL (not cached, just used for turn number)
            pipe_conn: PipeConnection for sending actions to DLL
        """
        new_turn_num = state.get("turn")
        
        with self._lock:
            # Detect new game: if turn goes backwards significantly (more than 10 turns),
            # or if we don't have a first turn tracked yet, treat it as a new game
            if new_turn_num is not None:
                if self._first_turn_of_game is None:
                    # First turn we've seen - start tracking this game
                    self._first_turn_of_game = new_turn_num
                    logger.info(f"Starting new game session (first turn: {new_turn_num})")
                elif new_turn_num < self._first_turn_of_game - 10:
                    # Turn went backwards significantly - new game started
                    logger.info(f"New game detected (turn {new_turn_num} < previous first turn {self._first_turn_of_game})")
                    self._first_turn_of_game = new_turn_num
            
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
        player_id = state.get("player_id", "?")
        # logger.info(f"🎮 TURN {turn_num} STARTED (Player {player_id})\nWaiting for LLM decisions...")

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
    
    @property
    def turn_active(self) -> bool:
        """Check if a turn is currently active."""
        with self._lock:
            return self._turn_active
    
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

    def _log_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        """Log a tool call (for tools that don't generate pipe messages)."""
        if name not in ("send_action", "end_turn"):
            logger.info(f"🔧 TOOL CALL: {name}\n{arguments}")

    def _log_tool_result(self, name: str, result: dict[str, Any], is_error: bool = False) -> None:
        """Log a tool result."""
        if name in ("send_action", "end_turn"):
            return
        if is_error:
            logger.warning(f"❌ TOOL ERROR: {name}: {result}")
        else:
            logger.info(f"✅ TOOL RESULT: {name}: {result}")

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return results."""
        self._log_tool_call(name, arguments)

        # Query tools - return dummy responses (will be replaced with DLL calls later)
        query_tools = {
            "get_game_state": lambda: self._get_game_state_dummy(
                category=arguments.get("category")
            ),
            "get_cities": lambda: self._get_cities_dummy(city_id=arguments.get("city_id")),
            "get_units": lambda: self._get_units_dummy(player_id=arguments.get("player_id")),
            "get_tech_tree": lambda: self._get_tech_tree_dummy(),
            "get_diplomacy": lambda: self._get_diplomacy_dummy(),
            "get_available_choices": lambda: self._get_available_choices_dummy(),
            "get_victory_progress": lambda: self._get_victory_progress_dummy(),
            "get_resources": lambda: self._get_resources_dummy(),
            "get_state_refresh": lambda: self._get_state_refresh_dummy(),
            "get_notifications": lambda: self._get_notifications_dummy(),
        }

        if name in query_tools:
            result = query_tools[name]()
            self._log_tool_result(name, result, is_error="error" in result)
            return result

        # Action tools
        if name == "send_action":
            action = arguments.get("action")
            if action is None:
                return {"error": "Missing required parameter 'action'"}
            if not isinstance(action, dict):
                return {"error": f"Parameter 'action' must be a dictionary, got {type(action).__name__}"}
            return self._send_action(action=action)

        # Turn control
        if name == "end_turn":
            return self._end_turn(notes=arguments.get("notes", ""))

        # Tools with validation
        if name == "acknowledge_notification":
            notification_id = arguments.get("notification_id")
            if notification_id is None:
                error = {"error": "Missing required parameter 'notification_id'"}
                self._log_tool_result(name, error, is_error=True)
                return error
            result = self._acknowledge_notification_dummy(notification_id)
            self._log_tool_result(name, result, is_error="error" in result)
            return result

        if name == "get_player_status":
            player_id = arguments.get("player_id")
            result = self._get_player_status_dummy(player_id=player_id)
            self._log_tool_result(name, result, is_error="error" in result)
            return result

        if name == "send_action_with_confirmation":
            action = arguments.get("action")
            if action is None:
                return {"error": "Missing required parameter 'action'"}
            if not isinstance(action, dict):
                return {"error": f"Parameter 'action' must be a dictionary, got {type(action).__name__}"}
            delay_seconds = arguments.get("delay_seconds", 0.5)
            query_type = arguments.get("query_type", "units")
            result = self._send_action_with_confirmation(
                action=action,
                delay_seconds=delay_seconds,
                query_type=query_type
            )
            self._log_tool_result(name, result, is_error="error" in result)
            return result

        if name == "ping":
            result = self._ping()
            self._log_tool_result(name, result, is_error="error" in result)
            return result

        # Unknown tool
        error = {"error": f"Unknown tool: {name}"}
        self._log_tool_result(name, error, is_error=True)
        return error

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
        action_kind = action.get("kind")
        if not action_kind:
            return {"error": "Action missing 'kind' field"}
        
        logger.debug(f"Turn {current_turn}: Preparing action '{action_kind}'")

        # Convert action to explicit message type per protocol
        # Protocol: actions are explicit message types, not wrapped in generic "action"
        # Extract 'kind' and use it as 'type', add request_id, keep other fields
        message = action.copy()
        message["type"] = action_kind
        message["request_id"] = str(uuid.uuid4())
        # Remove 'kind' since it's now 'type'
        if "kind" in message:
            del message["kind"]

        # Log outgoing message to JSONL
        log_msg = message.copy()
        log_msg["direction"] = "outgoing"
        self._message_logger.log_message(log_msg)

        # Send action (synchronous, blocks until result or timeout)
        try:
            # We'll use a 10s timeout for actions
            result = pipe_conn.send_action(message, timeout=10.0)
            
            if "error" in result:
                with self._lock:
                    self._action_errors += 1
                return result
            
            # Action succeeded or returned a result
            with self._lock:
                self._action_count += 1
                self._last_action_time = time.time()
            
            return result
        except Exception as e:
            with self._lock:
                self._action_errors += 1
            logger.error(f"Exception sending action: {e}", exc_info=True)
            return {"error": f"Failed to send action: {e}"}

    def _end_turn(self, notes: str = "") -> dict[str, Any]:
        """Signal that the LLM is done with its turn and wait for DLL confirmation.
        
        The DLL might block the end-turn request if there are pending units, 
        tech choices, etc. This method waits for the authoritative result.
        """
        with self._lock:
            if not self._turn_active:
                return {"error": "No active turn to end", "status": "error"}
            pipe_conn = self._pipe_conn
            current_turn = self._current_turn_number

        if not pipe_conn:
            return {"error": "No pipe connection available"}

        logger.info(f"LLM requesting end_turn (turn {current_turn})")

        # Log outgoing end_turn message to JSONL
        end_turn_msg = {"type": "end_turn", "request_id": str(uuid.uuid4()), "direction": "outgoing"}
        if current_turn is not None:
            end_turn_msg["turn"] = current_turn
        self._message_logger.log_message(end_turn_msg)

        # Send end_turn to DLL and wait for end_turn_result
        try:
            result = pipe_conn.send_end_turn(turn=current_turn, timeout=15.0)
            
            status = result.get("status", "unknown")
            
            if status == "success":
                # Only signal orchestrator that turn is done if DLL confirms success
                with self._lock:
                    self._turn_notes = notes
                    self._turn_active = False # Transition out of active state
                
                self._turn_ended.set()
                
                turn_info = f"Turn {current_turn}" if current_turn is not None else "Turn ?"
                logger.info(f"✅ {turn_info} ended successfully (confirmed by DLL)")
                return {
                    "status": "success",
                    "turn": current_turn,
                    "message": "Turn ended successfully"
                }
            
            elif status == "blocked":
                blocker = result.get("blocker", "unknown")
                logger.warning(f"❌ End turn blocked by: {blocker}")
                return {
                    "status": "blocked",
                    "blocker": blocker,
                    "message": f"Turn cannot end yet: {blocker}. Please resolve the blocker and try again."
                }
            
            elif status == "already_ended":
                logger.info("End turn requested but turn already ended")
                with self._lock:
                    self._turn_active = False
                self._turn_ended.set()
                return {
                    "status": "already_ended",
                    "message": "Turn has already been ended"
                }
            
            elif status == "timeout":
                logger.error("Timeout waiting for end_turn_result from DLL")
                return {
                    "status": "timeout",
                    "error": "DLL did not respond to end_turn request in time"
                }
            
            else:
                logger.error(f"Unexpected end_turn status: {status}")
                return {
                    "status": "error",
                    "error": f"DLL returned unexpected status: {status}",
                    "result": result
                }
                
        except Exception as e:
            logger.error(f"Exception during end_turn: {e}", exc_info=True)
            return {"error": f"Failed to end turn: {e}"}

    def _get_game_state_dummy(self, category: Optional[str] = None) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}

    def _get_cities_dummy(self, city_id: Optional[int] = None) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}

    def _get_units_dummy(self, player_id: Optional[int] = None) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}

    def _get_tech_tree_dummy(self) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}

    def _get_diplomacy_dummy(self) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}

    def _get_available_choices_dummy(self) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}

    def _get_victory_progress_dummy(self) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}

    def _get_resources_dummy(self) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}

    def _get_state_refresh_dummy(self) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}

    def _get_notifications_dummy(self) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"notifications": [], "count": 0, "message": "Dummy response - will query DLL directly"}

    def _acknowledge_notification_dummy(self, notification_id: int) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        if not isinstance(notification_id, int):
            return {"error": f"notification_id must be an integer, got {type(notification_id).__name__}"}
        return {"status": "acknowledged", "lookup_index": notification_id, "message": "Dummy response - will send to DLL"}

    def _get_player_status_dummy(self, player_id: Optional[int] = None) -> dict[str, Any]:
        """Dummy response - will be replaced with DLL call."""
        return {"message": "Dummy response - state caching removed, will query DLL directly"}
    
    def _send_action_with_confirmation(
        self,
        action: dict[str, Any],
        delay_seconds: float = 0.5,
        query_type: str = "units"
    ) -> dict[str, Any]:
        """Send an action and then query game state after a delay to confirm execution.
        
        This is useful for actions like unit moves where you want to verify the unit
        actually moved to the expected location.
        
        Args:
            action: Action dictionary to send
            delay_seconds: How long to wait before querying state (default 0.5)
            query_type: What to query after delay - "units" or "state" (default "units")
            
        Returns:
            Dictionary with action send status and query results
        """
        # Send the action (non-blocking)
        send_result = self._send_action(action)
        
        if "error" in send_result:
            return send_result
        
        # Wait for the delay
        time.sleep(delay_seconds)
        
        # Query state based on query_type (dummy responses for now)
        query_result = {}
        if query_type == "units":
            # Get units to check if move happened
            units_result = self._get_units_dummy()
            query_result = {
                "query_type": "units",
                "units": units_result
            }
        elif query_type == "state":
            # Get full game state
            state_result = self._get_game_state_dummy()
            query_result = {
                "query_type": "state",
                "state": state_result
            }
        else:
            query_result = {
                "error": f"Unknown query_type: {query_type}. Use 'units' or 'state'"
            }
        
        return {
            "action_sent": send_result,
            "confirmation_query": query_result,
            "delay_seconds": delay_seconds
        }
    
    def _ping(self) -> dict[str, Any]:
        """Ping the DLL to check connectivity and get server status.
        
        Sends a ping message to the DLL via the pipe connection and waits for a pong response.
        
        Returns:
            Dictionary with DLL response (pong), server status, timestamp, and turn information
        """
        with self._lock:
            if not self._turn_active:
                return {
                    "error": "Cannot ping - no active turn (no pipe connection available)",
                    "status": "error"
                }
            pipe_conn = self._pipe_conn
            turn_active = self._turn_active
            turn_number = self._current_turn_number
            action_count = self._action_count
            action_errors = self._action_errors
        
        if not pipe_conn:
            return {
                "error": "No pipe connection available",
                "status": "error"
            }
        
        # Send ping message to DLL
        ping_message = {
            "type": "ping",
            "request_id": str(uuid.uuid4())
        }
        
        # Log outgoing ping message to JSONL (before sending)
        log_ping = ping_message.copy()
        log_ping["direction"] = "outgoing"
        self._message_logger.log_message(log_ping)
        
        try:
            # Use send_request to send ping and wait for pong response
            # send_request will use our request_id (it only generates one if missing)
            result = pipe_conn.send_request(ping_message, timeout=5.0)
            
            # Check if we got a pong response
            if result.get("type") == "pong":
                return {
                    "status": "ok",
                    "server": "civ5-mcp",
                    "dll_response": "pong",
                    "timestamp": time.time(),
                    "turn_active": turn_active,
                    "turn_number": turn_number,
                    "action_count": action_count,
                    "action_errors": action_errors,
                    "message": "Pong! DLL is responding.",
                    "request_id": result.get("request_id")
                }
            elif "error" in result:
                return {
                    "status": "error",
                    "error": result.get("error"),
                    "message": "Failed to ping DLL",
                    "timestamp": time.time(),
                    "turn_active": turn_active,
                    "turn_number": turn_number
                }
            else:
                return {
                    "status": "unknown",
                    "dll_response": result,
                    "message": "Received unexpected response from DLL",
                    "timestamp": time.time(),
                    "turn_active": turn_active,
                    "turn_number": turn_number
                }
        except Exception as e:
            logger.error(f"Exception during ping: {e}", exc_info=True)
            return {
                "status": "error",
                "error": f"Failed to ping DLL: {e}",
                "timestamp": time.time(),
                "turn_active": turn_active,
                "turn_number": turn_number
            }
    
