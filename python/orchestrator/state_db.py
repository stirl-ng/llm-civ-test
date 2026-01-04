"""Database module for persistent game state tracking."""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import logging

logger = logging.getLogger(__name__)


class StateDatabase:
    """SQLite database for tracking game state history and notifications."""

    def __init__(self, db_path: str = "orchestrator_state.db"):
        """Initialize the state database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS game_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    turn INTEGER,
                    player_id INTEGER,
                    message_type TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    validated BOOLEAN DEFAULT 0,
                    validation_errors TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    notification_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data_json TEXT,
                    acknowledged BOOLEAN DEFAULT 0
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    turn INTEGER,
                    action_json TEXT NOT NULL,
                    response_json TEXT,
                    success BOOLEAN
                )
            """)
            
            # Indexes for faster queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_states_turn ON game_states(turn)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_states_timestamp ON game_states(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_ack ON notifications(acknowledged)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_turn ON actions(turn)")
            
            conn.commit()
            logger.info(f"Initialized state database at {self.db_path}")

    def save_state(
        self,
        state: dict[str, Any],
        validated: bool = False,
        validation_errors: Optional[str] = None
    ) -> int:
        """Save a game state to the database.
        
        Args:
            state: Game state dictionary
            validated: Whether state passed validation
            validation_errors: Validation error messages if any
            
        Returns:
            Database row ID
        """
        timestamp = datetime.now().timestamp()
        message_type = state.get("type", "unknown")
        turn = state.get("turn")
        player_id = state.get("player_id")
        state_json = json.dumps(state, sort_keys=True)
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    INSERT INTO game_states 
                    (timestamp, turn, player_id, message_type, state_json, validated, validation_errors)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (timestamp, turn, player_id, message_type, state_json, validated, validation_errors))
                conn.commit()
                row_id = cursor.lastrowid
                logger.debug(f"Saved state to database: turn={turn}, type={message_type}, id={row_id}")
                return row_id

    def get_latest_state(self, turn: Optional[int] = None) -> Optional[dict[str, Any]]:
        """Get the latest game state.
        
        Args:
            turn: Optional turn number to filter by
            
        Returns:
            Latest state dictionary or None
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                if turn is not None:
                    cursor = conn.execute("""
                        SELECT state_json FROM game_states 
                        WHERE turn = ? 
                        ORDER BY timestamp DESC LIMIT 1
                    """, (turn,))
                else:
                    cursor = conn.execute("""
                        SELECT state_json FROM game_states 
                        ORDER BY timestamp DESC LIMIT 1
                    """)
                row = cursor.fetchone()
                if row:
                    return json.loads(row["state_json"])
                return None

    def get_state_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent game states.
        
        Args:
            limit: Maximum number of states to return
            
        Returns:
            List of state dictionaries with metadata
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT id, timestamp, turn, player_id, message_type, 
                           validated, validation_errors, state_json
                    FROM game_states 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                return [
                    {
                        "id": row["id"],
                        "timestamp": row["timestamp"],
                        "turn": row["turn"],
                        "player_id": row["player_id"],
                        "message_type": row["message_type"],
                        "validated": bool(row["validated"]),
                        "validation_errors": row["validation_errors"],
                        "state": json.loads(row["state_json"])
                    }
                    for row in rows
                ]

    def add_notification(
        self,
        notification_type: str,
        message: str,
        data: Optional[dict[str, Any]] = None
    ) -> int:
        """Add a notification for the LLM.
        
        Args:
            notification_type: Type of notification (e.g., "turn_start", "error", "warning")
            message: Human-readable message
            data: Optional additional data
            
        Returns:
            Notification ID
        """
        timestamp = datetime.now().timestamp()
        data_json = json.dumps(data) if data else None
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    INSERT INTO notifications (timestamp, notification_type, message, data_json)
                    VALUES (?, ?, ?, ?)
                """, (timestamp, notification_type, message, data_json))
                conn.commit()
                row_id = cursor.lastrowid
                logger.info(f"Added notification: {notification_type} - {message}")
                return row_id

    def get_unacknowledged_notifications(self) -> list[dict[str, Any]]:
        """Get all unacknowledged notifications.
        
        Returns:
            List of notification dictionaries
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT id, timestamp, notification_type, message, data_json
                    FROM notifications 
                    WHERE acknowledged = 0
                    ORDER BY timestamp ASC
                """)
                rows = cursor.fetchall()
                return [
                    {
                        "id": row["id"],
                        "timestamp": row["timestamp"],
                        "type": row["notification_type"],
                        "message": row["message"],
                        "data": json.loads(row["data_json"]) if row["data_json"] else None
                    }
                    for row in rows
                ]

    def acknowledge_notification(self, notification_id: int) -> bool:
        """Mark a notification as acknowledged.
        
        Args:
            notification_id: Notification ID to acknowledge
            
        Returns:
            True if notification was found and acknowledged
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    UPDATE notifications 
                    SET acknowledged = 1 
                    WHERE id = ?
                """, (notification_id,))
                conn.commit()
                return cursor.rowcount > 0

    def acknowledge_all_notifications(self) -> int:
        """Mark all notifications as acknowledged.
        
        Returns:
            Number of notifications acknowledged
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    UPDATE notifications 
                    SET acknowledged = 1 
                    WHERE acknowledged = 0
                """)
                conn.commit()
                return cursor.rowcount

    def save_action(
        self,
        turn: Optional[int],
        action: dict[str, Any],
        response: Optional[dict[str, Any]] = None,
        success: Optional[bool] = None
    ) -> int:
        """Save an action and its response.
        
        Args:
            turn: Turn number
            action: Action dictionary
            response: Response dictionary
            success: Whether action succeeded
            
        Returns:
            Database row ID
        """
        timestamp = datetime.now().timestamp()
        action_json = json.dumps(action, sort_keys=True)
        response_json = json.dumps(response, sort_keys=True) if response else None
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    INSERT INTO actions (timestamp, turn, action_json, response_json, success)
                    VALUES (?, ?, ?, ?, ?)
                """, (timestamp, turn, action_json, response_json, success))
                conn.commit()
                return cursor.lastrowid

