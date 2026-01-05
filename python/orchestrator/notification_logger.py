"""Simple JSONL file logger for all DLL messages."""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import logging

logger = logging.getLogger(__name__)


class DLLMessageLogger:
    """Simple JSONL file logger for all messages from the DLL.
    
    Just appends everything we get from the DLL to a JSONL file.
    We can filter by type later when fetching.
    """

    def __init__(self, messages_file: str = "dll_messages.jsonl", acknowledgments_file: str = "acknowledgments.jsonl"):
        """Initialize the message logger.
        
        Args:
            messages_file: Path to JSONL file for all DLL messages
            acknowledgments_file: Path to JSONL file for acknowledgments
        """
        self.messages_file = Path(messages_file)
        self.acknowledgments_file = Path(acknowledgments_file)
        self._lock = threading.Lock()
        
        # Ensure files exist
        self.messages_file.touch(exist_ok=True)
        self.acknowledgments_file.touch(exist_ok=True)

    def log_message(self, message: dict[str, Any]) -> None:
        """Append a message to the JSONL file.
        
        Args:
            message: Full message dict from DLL (all fields preserved)
        """
        # Create a copy to avoid modifying the original
        msg_copy = message.copy()
        
        # Add timestamp if not present
        if "timestamp" not in msg_copy:
            msg_copy["timestamp"] = datetime.now().timestamp()
        
        with self._lock:
            with open(self.messages_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg_copy) + "\n")

    def log_acknowledgment(self, notification_id: int, lookup_index: Optional[int] = None) -> None:
        """Log that a notification was acknowledged.
        
        Args:
            notification_id: ID of the notification (if we're tracking by ID)
            lookup_index: Lookup index of the notification (from DLL)
        """
        ack = {
            "timestamp": datetime.now().timestamp(),
            "notification_id": notification_id,
            "lookup_index": lookup_index,
        }
        
        with self._lock:
            with open(self.acknowledgments_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(ack) + "\n")

    def get_messages(
        self,
        message_type: Optional[str] = None,
        min_turn: Optional[int] = None,
        player_id: Optional[int] = None,
        unacknowledged_only: bool = False
    ) -> list[dict[str, Any]]:
        """Get messages from the JSONL file.
        
        Args:
            message_type: Optional message type to filter by (e.g., "notification", "turn_start")
            min_turn: Optional minimum turn number to filter by
            player_id: Optional player ID to filter by
            unacknowledged_only: If True, only return unacknowledged notifications (only applies to notifications)
        
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
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse message line: {e}")
            
            # Load acknowledged notifications if needed
            acknowledged_lookup_indices = set()
            if unacknowledged_only and self.acknowledgments_file.exists():
                with open(self.acknowledgments_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ack = json.loads(line)
                            if "lookup_index" in ack and ack["lookup_index"] is not None:
                                acknowledged_lookup_indices.add(ack["lookup_index"])
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse acknowledgment line: {e}")
            
            # Filter messages
            filtered = []
            for msg in messages:
                # Filter by type
                if message_type is not None:
                    msg_type = msg.get("type")
                    if msg_type != message_type and msg_type != f"game_{message_type}":
                        continue
                
                # Filter by turn
                if min_turn is not None:
                    msg_turn = msg.get("turn")
                    if msg_turn is not None and msg_turn < min_turn:
                        continue
                
                # Filter by player
                if player_id is not None:
                    msg_player = msg.get("player_id")
                    if msg_player != player_id:
                        continue
                
                # Filter acknowledged (only for notifications)
                if unacknowledged_only:
                    msg_type = msg.get("type")
                    if msg_type in ("notification", "game_notification"):
                        lookup_idx = msg.get("lookup_index")
                        if lookup_idx is not None and lookup_idx in acknowledged_lookup_indices:
                            continue
                
                filtered.append(msg)
            
            return filtered

    def acknowledge_notification(self, lookup_index: int) -> bool:
        """Mark a notification as acknowledged by lookup_index.
        
        Args:
            lookup_index: Lookup index of the notification to acknowledge
        
        Returns:
            True if acknowledged (always returns True, just logs it)
        """
        self.log_acknowledgment(notification_id=-1, lookup_index=lookup_index)
        return True

