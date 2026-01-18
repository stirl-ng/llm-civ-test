"""GameState - Single source of truth for game metadata.

Thread-safe class that holds game metadata (turn, game_id, session_id, etc.)
Updated from DLL messages, read by MCP server and other components.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GameState:
    """Thread-safe game state metadata storage.

    Holds essential game metadata updated from DLL messages.
    This is the single source of truth for current turn, game ID, etc.
    """

    def __init__(self):
        """Initialize empty game state."""
        self._lock = threading.Lock()

        # Core identifiers
        self._turn_number: Optional[int] = None
        self._game_id: Optional[int] = None
        self._session_id: Optional[int] = None
        self._player_id: Optional[int] = None
        self._player_name: Optional[str] = None

        # Turn blockers (from turn_start message)
        self._blockers: list[dict[str, Any]] = []

        # Connection status
        self._connected: bool = False
        self._last_update_time: float = 0.0

    def update_from_message(self, message: dict[str, Any]) -> None:
        """Update state from a DLL message (turn_start, heartbeat, etc.).

        Args:
            message: Message dict from DLL
        """
        with self._lock:
            if not self._connected:
                self._connected = True
                logger.info("Game connection established")

            # Update turn
            if "turn" in message:
                new_turn = message["turn"]
                if self._turn_number != new_turn:
                    logger.debug(f"Turn: {self._turn_number} → {new_turn}")
                    self._turn_number = new_turn

            # Update game ID
            if "game_id" in message:
                new_game_id = message["game_id"]
                if self._game_id != new_game_id:
                    logger.debug(f"Game ID: {self._game_id} → {new_game_id}")
                    self._game_id = new_game_id

            # Update session ID
            if "session_id" in message:
                new_session_id = message["session_id"]
                if self._session_id != new_session_id:
                    logger.debug(f"Session ID: {self._session_id} → {new_session_id}")
                    self._session_id = new_session_id

            # Update player info
            if "player_id" in message:
                new_player_id = message["player_id"]
                if self._player_id != new_player_id:
                    logger.debug(f"Player ID: {self._player_id} → {new_player_id}")
                    self._player_id = new_player_id

            if "player_name" in message:
                new_player_name = message["player_name"]
                if self._player_name != new_player_name:
                    logger.debug(f"Player: {self._player_name} → {new_player_name}")
                    self._player_name = new_player_name

            # Update blockers from turn_start messages
            if "blockers" in message:
                self._blockers = message["blockers"]
                if self._blockers:
                    logger.debug(f"Blockers: {[b.get('type') for b in self._blockers]}")

            self._last_update_time = time.time()

    def get_metadata(self) -> dict[str, Any]:
        """Get all metadata as a dictionary.

        Returns:
            Dictionary with all game state metadata
        """
        with self._lock:
            return {
                "turn_number": self._turn_number,
                "game_id": self._game_id,
                "session_id": self._session_id,
                "player_id": self._player_id,
                "player_name": self._player_name,
                "blockers": self._blockers,
                "connected": self._connected,
                "last_update_time": self._last_update_time,
            }

    def reset(self) -> None:
        """Reset state (e.g., on disconnect or new game)."""
        with self._lock:
            self._turn_number = None
            self._game_id = None
            self._session_id = None
            self._player_id = None
            self._player_name = None
            self._blockers = []
            self._connected = False
            self._last_update_time = 0.0
            logger.info("Game state reset")

    # Properties for convenient access

    @property
    def turn_number(self) -> Optional[int]:
        """Current turn number."""
        with self._lock:
            return self._turn_number

    @property
    def game_id(self) -> Optional[int]:
        """Game ID (persists across saves)."""
        with self._lock:
            return self._game_id

    @property
    def session_id(self) -> Optional[int]:
        """Session ID (changes per pipe connection)."""
        with self._lock:
            return self._session_id

    @property
    def player_id(self) -> Optional[int]:
        """Current player ID."""
        with self._lock:
            return self._player_id

    @property
    def player_name(self) -> Optional[str]:
        """Current player name."""
        with self._lock:
            return self._player_name

    @property
    def connected(self) -> bool:
        """Whether game is connected."""
        with self._lock:
            return self._connected

    @property
    def last_update_time(self) -> float:
        """Timestamp of last update."""
        with self._lock:
            return self._last_update_time

    @property
    def blockers(self) -> list[dict[str, Any]]:
        """Current end-turn blockers."""
        with self._lock:
            return self._blockers.copy()
