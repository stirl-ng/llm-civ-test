"""
Turn Manager - Handles interactive turn protocol with DLL.

Manages the turn lifecycle:
1. Receives turn_start from DLL
2. Caches state for LLM queries
3. Forwards actions to DLL, returns results
4. Sends end_turn, waits for ack
"""

import json
import logging
import threading
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TurnManager:
    """Manages interactive turn communication between LLM and DLL.

    Thread-safe: HTTP handlers can call execute_action() while main
    thread waits for turn to end.
    """

    def __init__(self, transport, action_timeout: float = 30.0):
        """Initialize turn manager.

        Args:
            transport: Transport object for DLL communication (read_line/write_line)
            action_timeout: Timeout in seconds for individual actions
        """
        self.transport = transport
        self.action_timeout = action_timeout

        # State
        self._current_state: Optional[dict[str, Any]] = None
        self._turn_number: Optional[int] = None
        self._player_id: Optional[int] = None

        # Turn lifecycle
        self._turn_active = False
        self._turn_ended = threading.Event()

        # Thread safety
        self._lock = threading.Lock()
        self._action_lock = threading.Lock()  # Serialize DLL actions

    @property
    def current_state(self) -> Optional[dict[str, Any]]:
        """Get current cached game state."""
        return self._current_state

    @property
    def turn_active(self) -> bool:
        """Check if a turn is currently active."""
        return self._turn_active

    @property
    def turn_number(self) -> Optional[int]:
        """Get current turn number."""
        return self._turn_number

    def start_turn(self, turn_start_msg: dict[str, Any]) -> None:
        """Start a new turn from a turn_start message.

        Args:
            turn_start_msg: The turn_start message from DLL
        """
        with self._lock:
            self._current_state = turn_start_msg.get("state", {})
            self._turn_number = turn_start_msg.get("turn")
            self._player_id = turn_start_msg.get("player_id")
            self._turn_active = True
            self._turn_ended.clear()

        logger.info(f"Turn {self._turn_number} started for player {self._player_id}")

    def wait_for_turn_end(self, timeout: Optional[float] = None) -> bool:
        """Block until turn ends (LLM calls end_turn).

        Args:
            timeout: Max seconds to wait (None = wait forever)

        Returns:
            True if turn ended normally, False if timed out
        """
        ended = self._turn_ended.wait(timeout=timeout)

        with self._lock:
            self._turn_active = False

        return ended

    def execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute an action via the DLL and return the result.

        This is called by the HTTP handler when LLM uses send_action tool.
        Thread-safe and serialized (one action at a time).

        Args:
            action: The action to execute (e.g., {"kind": "move_unit", ...})

        Returns:
            The action result from DLL including state_delta
        """
        if not self._turn_active:
            return {"success": False, "error": "No active turn"}

        with self._action_lock:
            request_id = str(uuid.uuid4())

            # Build and send action message
            msg = {
                "type": "action",
                "request_id": request_id,
                "action": action
            }

            logger.debug(f"Sending action: {action.get('kind', 'unknown')}")
            self.transport.write_line(json.dumps(msg))

            # Read response
            line = self.transport.read_line()
            if not line:
                return {"success": False, "error": "DLL disconnected"}

            try:
                result = json.loads(line.strip())
            except json.JSONDecodeError as e:
                return {"success": False, "error": f"Invalid JSON from DLL: {e}"}

            # Verify it's the response we expect
            if result.get("type") != "action_result":
                logger.warning(f"Unexpected message type: {result.get('type')}")
                return {"success": False, "error": f"Unexpected response: {result.get('type')}"}

            if result.get("request_id") != request_id:
                logger.warning(f"Request ID mismatch")

            # Update cached state with delta
            state_delta = result.get("state_delta")
            if state_delta:
                self._merge_state_delta(state_delta)

            logger.debug(f"Action result: success={result.get('success')}")
            return result

    def request_state_refresh(self) -> dict[str, Any]:
        """Request full state refresh from DLL.

        Returns:
            The full game state
        """
        if not self._turn_active:
            return {"error": "No active turn"}

        with self._action_lock:
            request_id = str(uuid.uuid4())

            msg = {
                "type": "get_state",
                "request_id": request_id
            }

            self.transport.write_line(json.dumps(msg))

            line = self.transport.read_line()
            if not line:
                return {"error": "DLL disconnected"}

            try:
                result = json.loads(line.strip())
            except json.JSONDecodeError as e:
                return {"error": f"Invalid JSON: {e}"}

            if result.get("type") == "state_refresh":
                with self._lock:
                    self._current_state = result.get("state", {})
                return self._current_state

            return {"error": f"Unexpected response: {result.get('type')}"}

    def end_turn(self, notes: str = "") -> dict[str, Any]:
        """End the current turn.

        Sends end_turn to DLL, waits for ack, signals turn ended.

        Args:
            notes: Optional notes about the turn

        Returns:
            The turn_end_ack from DLL
        """
        if not self._turn_active:
            return {"success": False, "error": "No active turn"}

        with self._action_lock:
            msg = {"type": "end_turn"}
            self.transport.write_line(json.dumps(msg))

            line = self.transport.read_line()
            if not line:
                self._turn_ended.set()
                return {"success": False, "error": "DLL disconnected"}

            try:
                ack = json.loads(line.strip())
            except json.JSONDecodeError as e:
                self._turn_ended.set()
                return {"success": False, "error": f"Invalid JSON: {e}"}

            logger.info(f"Turn {self._turn_number} ended")

            # Signal turn ended
            self._turn_ended.set()

            return {
                "success": True,
                "turn": self._turn_number,
                "ack": ack
            }

    def _merge_state_delta(self, delta: dict[str, Any]) -> None:
        """Merge state delta into current state.

        Merge rules:
        - Scalars: replace
        - Arrays with IDs (units, cities): upsert by ID
        - *_removed arrays: delete by ID
        - revealed_tiles: append
        """
        with self._lock:
            if not self._current_state:
                return

            state = self._current_state

            for key, value in delta.items():
                if key.endswith("_removed"):
                    # Handle removals (e.g., units_removed -> remove from units)
                    base_key = key[:-8]  # Remove "_removed" suffix
                    if base_key in state and isinstance(state[base_key], list):
                        removed_ids = set(value)
                        state[base_key] = [
                            item for item in state[base_key]
                            if item.get("id") not in removed_ids
                        ]

                elif key == "revealed_tiles":
                    # Append revealed tiles
                    if "revealed_tiles" not in state:
                        state["revealed_tiles"] = []
                    state["revealed_tiles"].extend(value)

                elif key == "notifications":
                    # Append notifications
                    if "notifications" not in state:
                        state["notifications"] = []
                    state["notifications"].extend(value)

                elif isinstance(value, list) and value and isinstance(value[0], dict) and "id" in value[0]:
                    # Upsert by ID for lists of objects with IDs
                    if key not in state:
                        state[key] = []

                    existing_ids = {item.get("id"): i for i, item in enumerate(state[key])}

                    for item in value:
                        item_id = item.get("id")
                        if item_id in existing_ids:
                            # Update existing
                            state[key][existing_ids[item_id]] = item
                        else:
                            # Add new
                            state[key].append(item)

                else:
                    # Scalar or unknown structure - replace
                    state[key] = value

            logger.debug(f"Merged state delta: {list(delta.keys())}")
