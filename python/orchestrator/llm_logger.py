"""JSONL file logger for LLM API requests and responses."""

import json
import threading
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .game_state import GameState

# Module-level singleton instance
_instance: Optional["LLMLogger"] = None
_instance_lock = threading.Lock()

# Module-level reference to GameState (set by orchestrator)
_game_state_ref: Optional["GameState"] = None
_game_state_lock = threading.Lock()


def set_game_state(game_state: Optional["GameState"]) -> None:
    """Set the GameState reference for the logger to use.
    
    Called by orchestrator during initialization.
    
    Args:
        game_state: GameState instance to use for metadata, or None to clear
    """
    global _game_state_ref
    with _game_state_lock:
        _game_state_ref = game_state


def get_llm_logger() -> "LLMLogger":
    """Get the singleton LLMLogger instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LLMLogger()
    return _instance


class LLMLogger:
    """JSONL file logger for LLM API requests and responses.
    
    Logs only the latest message addition (not full conversation history)
    along with metadata (turn, game_id, session_id, model) for each entry.
    This keeps logs compact and queryable, similar to Claude Code's approach
    but with per-turn granularity.
    """

    def __init__(self, messages_file: Optional[str] = None):
        """Initialize the LLM logger.
        
        Args:
            messages_file: Path to JSONL file for LLM API messages. If None, uses
                absolute path based on module location: python/logs/llm_messages.jsonl
        """
        if messages_file is None:
            # Use absolute path based on module location
            module_dir = Path(__file__).parent.parent
            messages_file = str(module_dir / "logs" / "llm_messages.jsonl")
        
        self.messages_file = Path(messages_file)
        self._lock = threading.Lock()
        
        # Ensure directory exists
        self.messages_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Ensure file exists
        self.messages_file.touch(exist_ok=True)

    def _get_game_metadata(self) -> dict[str, Any]:
        """Get current game metadata from module-level GameState reference.
        
        Returns:
            Dictionary with turn, game_id, session_id (or empty if not available)
        """
        global _game_state_ref
        with _game_state_lock:
            game_state = _game_state_ref
        
        if game_state is None:
            return {}
        
        try:
            return {
                "turn": game_state.turn_number,
                "game_id": game_state.game_id,
                "session_id": game_state.session_id,
            }
        except AttributeError:
            return {}

    def log_request(
        self, 
        model: str, 
        messages: list[dict[str, Any]], 
        **kwargs: Any
    ) -> str:
        """Log an LLM API request.
        
        Only logs the latest message (last entry in messages array) to keep logs compact.
        Automatically includes game metadata (turn, game_id, session_id) if available.
        
        Args:
            model: Model name/identifier
            messages: Chat messages sent to LLM (full conversation history)
            **kwargs: Additional request parameters (temperature, etc.)
        
        Returns:
            UUID of the logged request (for correlating with response)
        """
        from datetime import datetime
        from uuid import uuid4
        
        request_uuid = str(uuid4())
        
        # Extract only the latest message (most recent addition)
        # This is the key change: instead of logging the entire conversation,
        # we only log what was just added
        latest_message = messages[-1] if messages else {}
        
        # Get game metadata automatically
        metadata = self._get_game_metadata()
        
        log_entry = {
            "type": "llm_request",
            "timestamp": datetime.now().isoformat(),
            "uuid": request_uuid,
            "model": model,
            "latest_message": latest_message,  # Only latest, not full history
            **metadata,  # turn, game_id, session_id if available
            **{k: v for k, v in kwargs.items() if k not in metadata},  # temperature, etc.
        }
        
        with self._lock:
            with open(self.messages_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        
        return request_uuid

    def log_response(
        self, 
        request_uuid: str, 
        response: str,
        **kwargs: Any
    ) -> None:
        """Log an LLM API response.
        
        Automatically includes game metadata (turn, game_id, session_id) if available.
        
        Args:
            request_uuid: UUID of the corresponding request
            response: Response text from LLM
            **kwargs: Additional response metadata
        """
        from datetime import datetime
        
        # Get game metadata automatically
        metadata = self._get_game_metadata()
        
        log_entry = {
            "type": "llm_response",
            "timestamp": datetime.now().isoformat(),
            "request_uuid": request_uuid,
            "response": response,
            **metadata,  # turn, game_id, session_id if available
            **kwargs,
        }
        
        with self._lock:
            with open(self.messages_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")

