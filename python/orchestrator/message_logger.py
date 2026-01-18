"""Unified JSONL message logger for game events and LLM interactions.

Replaces game_logger.py and llm_logger.py with a single, simpler logger.
All messages go to one file with consistent metadata for easy querying.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from .game_state import GameState

logger = logging.getLogger(__name__)

# Module-level singleton
_instance: Optional["MessageLogger"] = None
_instance_lock = threading.Lock()


def get_message_logger() -> "MessageLogger":
    """Get the singleton MessageLogger instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MessageLogger()
    return _instance


class MessageLogger:
    """Unified JSONL logger for all message types.

    Message types (distinguished by 'type' field):
    - DLL events: turn_start, turn_complete, heartbeat, notification, game_start
    - Tool calls: tool_request, tool_response
    - LLM calls: llm_request, llm_response

    All messages automatically get:
    - timestamp: ISO format
    - uuid: unique identifier
    - direction: 'incoming' or 'outgoing'
    - Game metadata (turn, game_id, session_id) if GameState is set
    """

    def __init__(self, log_file: Optional[Path] = None):
        """Initialize the message logger.

        Args:
            log_file: Path to JSONL file. Defaults to python/logs/messages.jsonl
        """
        if log_file is None:
            module_dir = Path(__file__).parent.parent
            log_file = module_dir / "logs" / "messages.jsonl"

        self.log_file = Path(log_file)
        self._lock = threading.Lock()
        self._game_state: Optional["GameState"] = None

        # Manual overrides for when GameState isn't available (e.g., run.py)
        self._manual_turn: Optional[int] = None
        self._manual_game_id: Optional[int] = None

        # Ensure directory and file exist
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.touch(exist_ok=True)

    def set_game_state(self, game_state: Optional["GameState"]) -> None:
        """Set GameState reference for automatic metadata injection.

        Args:
            game_state: GameState instance, or None to clear
        """
        with self._lock:
            self._game_state = game_state

    def set_turn(self, turn: Optional[int], game_id: Optional[int] = None) -> None:
        """Manually set turn/game_id (for use when GameState isn't available).

        Args:
            turn: Current turn number
            game_id: Optional game ID
        """
        with self._lock:
            self._manual_turn = turn
            if game_id is not None:
                self._manual_game_id = game_id

    def _get_game_metadata(self) -> dict[str, Any]:
        """Get current game metadata from GameState or manual overrides."""
        # Try GameState first
        if self._game_state is not None:
            try:
                return {
                    "turn": self._game_state.turn_number,
                    "game_id": self._game_state.game_id,
                    "session_id": self._game_state.session_id,
                    "player_id": self._game_state.player_id,
                }
            except AttributeError:
                pass

        # Fall back to manual values
        result = {}
        if self._manual_turn is not None:
            result["turn"] = self._manual_turn
        if self._manual_game_id is not None:
            result["game_id"] = self._manual_game_id
        return result

    def log(
        self,
        message: dict[str, Any],
        direction: Optional[str] = None,
        **extra: Any
    ) -> str:
        """Log a message to the JSONL file.

        Args:
            message: Message dict (must have 'type' field)
            direction: 'incoming' or 'outgoing' (optional, can be in message)
            **extra: Additional fields to add

        Returns:
            UUID of the logged message
        """
        # Create a copy to avoid modifying original
        entry = message.copy()

        # Add/override standard fields
        if "timestamp" not in entry:
            entry["timestamp"] = datetime.now().isoformat()

        msg_uuid = entry.get("uuid") or str(uuid4())
        entry["uuid"] = msg_uuid

        if direction and "direction" not in entry:
            entry["direction"] = direction

        # Add game metadata (don't override existing values)
        metadata = self._get_game_metadata()
        for key, value in metadata.items():
            if key not in entry and value is not None:
                entry[key] = value

        # Add extra fields
        for key, value in extra.items():
            if key not in entry:
                entry[key] = value

        # Write to file
        with self._lock:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

        return msg_uuid

    def log_llm_request(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any
    ) -> str:
        """Log an LLM API request (convenience method).

        Only logs the latest message to keep logs compact.

        Args:
            model: Model name
            messages: Full conversation history
            **kwargs: Additional params (temperature, etc.)

        Returns:
            UUID for correlating with response
        """
        latest_message = messages[-1] if messages else {}

        return self.log({
            "type": "llm_request",
            "model": model,
            "latest_message": latest_message,
            **kwargs,
        }, direction="outgoing")

    def log_llm_response(self, request_uuid: str, response: str, **kwargs: Any) -> str:
        """Log an LLM API response (convenience method).

        Args:
            request_uuid: UUID of corresponding request
            response: Response text from LLM
            **kwargs: Additional metadata

        Returns:
            UUID of response log entry
        """
        return self.log({
            "type": "llm_response",
            "request_uuid": request_uuid,
            "response": response,
            **kwargs,
        }, direction="incoming")

    def query(
        self,
        message_type: Optional[str] = None,
        direction: Optional[str] = None,
        turn: Optional[int] = None,
        game_id: Optional[int] = None,
        session_id: Optional[int] = None,
        player_id: Optional[int] = None,
        limit: int = 100,
        since_turn: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Query messages with filters.

        Args:
            message_type: Filter by type (e.g., 'turn_start', 'llm_request')
            direction: Filter by direction ('incoming' or 'outgoing')
            turn: Filter by exact turn number
            game_id: Filter by game ID
            session_id: Filter by session ID
            player_id: Filter by player ID
            limit: Maximum messages to return (default 100)
            since_turn: Filter messages from this turn onwards

        Returns:
            List of matching messages, most recent first
        """
        messages = []

        with self._lock:
            if not self.log_file.exists():
                return []

            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Apply filters
                    if message_type and msg.get("type") != message_type:
                        continue
                    if direction and msg.get("direction") != direction:
                        continue
                    if turn is not None and msg.get("turn") != turn:
                        continue
                    if game_id is not None and msg.get("game_id") != game_id:
                        continue
                    if session_id is not None and msg.get("session_id") != session_id:
                        continue
                    if player_id is not None and msg.get("player_id") != player_id:
                        continue
                    if since_turn is not None:
                        msg_turn = msg.get("turn")
                        if msg_turn is not None and msg_turn < since_turn:
                            continue

                    # Skip deleted messages
                    if "deleted" in msg:
                        continue

                    messages.append(msg)

        # Return most recent first, limited
        return list(reversed(messages))[:limit]

    def get_notifications(
        self,
        game_id: Optional[int] = None,
        since_turn: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Get notification messages (convenience method).

        Args:
            game_id: Filter by game ID (uses current if not specified)
            since_turn: Only get notifications from this turn onwards

        Returns:
            List of notification messages
        """
        if game_id is None:
            metadata = self._get_game_metadata()
            game_id = metadata.get("game_id")

        return self.query(
            message_type="notification",
            game_id=game_id,
            since_turn=since_turn,
            limit=1000,
        )
