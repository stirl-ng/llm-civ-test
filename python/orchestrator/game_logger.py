"""JSONL file logger for all game messages from the DLL."""

import json
import threading
from pathlib import Path
from typing import Any, Optional

# Module-level singleton instance
_instance: Optional["GameLogger"] = None
_instance_lock = threading.Lock()


def get_game_logger() -> "GameLogger":
    """Get the singleton GameLogger instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = GameLogger()
    return _instance


class GameLogger:
    """JSONL file logger for all game messages from the DLL.
    
    Logs all messages from the DLL (turn_start, notifications, action results, etc.)
    to JSONL files for later querying and analysis.
    """

    def __init__(self, messages_file: str = "logs/dll_messages.jsonl"):
        """Initialize the game logger.
        
        Args:
            messages_file: Path to JSONL file for all DLL messages
        """
        self.messages_file = Path(messages_file)
        self._lock = threading.Lock()
        
        # Ensure directory exists
        self.messages_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Ensure files exist
        self.messages_file.touch(exist_ok=True)

    def log_message(self, message: dict[str, Any]) -> None:
        """Append a message to the JSONL file.
        
        Args:
            message: Full message dict from DLL (all fields preserved)
        """
        # Create a copy to avoid modifying the original
        msg_copy = message.copy()
        
        # Add timestamp if not present
        if "timestamp" not in msg_copy:
            from datetime import datetime
            msg_copy["timestamp"] = datetime.now().isoformat()

        if "uuid" not in msg_copy:
            from uuid import uuid4
            msg_copy["uuid"] = str(uuid4())

        with self._lock:
            with open(self.messages_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg_copy) + "\n")

    def get_messages(
        self,
        message_type: Optional[str] = None,
        turn_number: Optional[int] = None,
        player_id: Optional[int] = None,
        game_id: Optional[int] = None,
        session_id: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Get messages from the JSONL file.

        Args:
            message_type: Optional message type to filter by (e.g., "notification", "turn_start")
            turn_number: Optional turn number to filter by
            player_id: Optional player ID to filter by
            game_id: Optional game ID to filter by (from mapRandomSeed, persists across saves)
            session_id: Optional session ID to filter by (changes on each pipe connection)

        Returns:
            List of message dictionaries
        """
        with self._lock:
            # Load all messages
            messages = []
            if self.messages_file.exists():
                with open(self.messages_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass  # Skip malformed lines
            
            # Filter messages
            filtered = []
            for msg in messages:
                # Filter by type
                if message_type is not None:
                    msg_type = msg.get("type")
                    if msg_type != message_type and msg_type != f"game_{message_type}":
                        continue
                
                # Filter by turn
                if turn_number is not None:
                    msg_turn = msg.get("turn")
                    if msg_turn is not None and msg_turn < turn_number:
                        continue
                
                # Filter by player
                if player_id is not None:
                    msg_player = msg.get("player_id")
                    if msg_player != player_id:
                        continue

                # Filter by game_id
                if game_id is not None:
                    msg_game_id = msg.get("game_id")
                    if msg_game_id != game_id:
                        continue

                # Filter by session_id
                if session_id is not None:
                    msg_session_id = msg.get("session_id")
                    if msg_session_id != session_id:
                        continue

                filtered.append(msg)
            
            return filtered
