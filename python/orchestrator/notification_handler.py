"""Notification handler for alerting LLM about incoming DLL messages."""

import logging
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


NotificationCallback = Callable[[str, str, Optional[dict[str, Any]]], None]


class NotificationHandler:
    """Handles notifications from DLL to alert LLM."""

    def __init__(self):
        """Initialize the notification handler."""
        self._callbacks: list[NotificationCallback] = []
        self._lock = threading.Lock()
        self._enabled = True

    def register_callback(self, callback: NotificationCallback) -> None:
        """Register a callback for notifications.
        
        Args:
            callback: Function that receives (notification_type, message, data)
        """
        with self._lock:
            self._callbacks.append(callback)
            logger.debug(f"Registered notification callback: {callback}")

    def unregister_callback(self, callback: NotificationCallback) -> None:
        """Unregister a callback.
        
        Args:
            callback: Callback to remove
        """
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
                logger.debug(f"Unregistered notification callback: {callback}")

    def notify(
        self,
        notification_type: str,
        message: str,
        data: Optional[dict[str, Any]] = None
    ) -> None:
        """Send a notification to all registered callbacks.
        
        Args:
            notification_type: Type of notification (e.g., "turn_start", "error", "warning")
            message: Human-readable message
            data: Optional additional data
        """
        if not self._enabled:
            return
        
        with self._lock:
            callbacks = list(self._callbacks)  # Copy to avoid lock during callback
        
        logger.info(f"Notification [{notification_type}]: {message}")
        
        for callback in callbacks:
            try:
                callback(notification_type, message, data)
            except Exception as e:
                logger.error(f"Error in notification callback {callback}: {e}", exc_info=True)

    def notify_turn_start(self, turn: int, player_id: int, state: dict[str, Any]) -> None:
        """Notify about a new turn starting.
        
        Args:
            turn: Turn number
            player_id: Player ID
            state: Game state
        """
        self.notify(
            "turn_start",
            f"Turn {turn} started for player {player_id}",
            {"turn": turn, "player_id": player_id, "state_summary": self._summarize_state(state)}
        )

    def notify_state_received(self, msg_type: str, turn: Optional[int] = None) -> None:
        """Notify about receiving a state message.
        
        Args:
            msg_type: Message type
            turn: Turn number if available
        """
        msg = f"Received {msg_type} message"
        if turn is not None:
            msg += f" for turn {turn}"
        self.notify("state_update", msg, {"type": msg_type, "turn": turn})

    def notify_validation_error(self, errors: str, state: dict[str, Any]) -> None:
        """Notify about validation errors.
        
        Args:
            errors: Error message
            state: State that failed validation
        """
        self.notify(
            "validation_error",
            f"State validation failed: {errors}",
            {"errors": errors, "state_type": state.get("type")}
        )

    def notify_consistency_warning(self, warning: str, previous_turn: Optional[int], new_turn: Optional[int]) -> None:
        """Notify about state consistency issues.
        
        Args:
            warning: Warning message
            previous_turn: Previous turn number
            new_turn: New turn number
        """
        self.notify(
            "consistency_warning",
            f"State consistency issue: {warning}",
            {"warning": warning, "previous_turn": previous_turn, "new_turn": new_turn}
        )

    def notify_pipe_error(self, error: str) -> None:
        """Notify about pipe communication errors.
        
        Args:
            error: Error message
        """
        self.notify("pipe_error", f"Pipe communication error: {error}", {"error": error})

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable notifications.
        
        Args:
            enabled: Whether to enable notifications
        """
        with self._lock:
            self._enabled = enabled
            logger.info(f"Notifications {'enabled' if enabled else 'disabled'}")

    def _summarize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Create a summary of state for notifications.
        
        Args:
            state: Full state dictionary
            
        Returns:
            Summary dictionary
        """
        inner_state = state.get("state", {})
        return {
            "turn": state.get("turn"),
            "player_id": state.get("player_id"),
            "players_alive": inner_state.get("playersAlive"),
            "cities_count": len(inner_state.get("cities", [])),
            "units_count": len(inner_state.get("units", [])),
        }

