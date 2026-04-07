"""Thread-safe pub/sub event broadcaster for SSE push.

Each subscriber gets a Queue of event dicts. Events are filtered by player_id
if supplied at subscribe time, allowing future multi-player scoping.
"""

from __future__ import annotations

import queue
import threading
from typing import Optional


class EventBroadcaster:
    """Thread-safe pub/sub bus. Each subscriber gets a Queue of event dicts."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: list[tuple[queue.Queue, Optional[int]]] = []
        self._pending_turn_start: Optional[dict] = None  # replayed to late subscribers

    def subscribe(self, player_id: Optional[int] = None) -> queue.Queue:
        """Register subscriber. player_id=None means receive all events.

        Late subscribers (connecting after turn_start fired) receive the last
        pending turn_start immediately so they don't miss their turn.

        Args:
            player_id: If set, only events for this player_id are delivered.
                       Pass None to receive all events regardless of player.

        Returns:
            Queue that will receive event dicts as they are emitted.
        """
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.append((q, player_id))
            # Replay pending turn_start to catch up late subscribers
            if self._pending_turn_start is not None:
                event_player_id = self._pending_turn_start.get("player_id")
                if player_id is None or player_id == event_player_id:
                    try:
                        q.put_nowait(self._pending_turn_start)
                    except queue.Full:
                        pass
        return q

    def has_pending_turn(self) -> bool:
        with self._lock:
            return self._pending_turn_start is not None

    def unsubscribe(self, q: queue.Queue) -> None:
        """Remove a subscriber queue."""
        with self._lock:
            self._subscribers = [(s, p) for s, p in self._subscribers if s is not q]

    def emit(self, event_type: str, data: dict) -> None:
        """Broadcast an event to all matching subscribers.

        Args:
            event_type: SSE event name (e.g. "turn_start", "disconnected").
            data: Event payload dict. May contain "player_id" for filtering.
        """
        payload = {"event": event_type, **data}
        player_id = data.get("player_id")
        with self._lock:
            if event_type == "turn_start":
                self._pending_turn_start = payload
            elif event_type == "disconnected":
                self._pending_turn_start = None
            for q, filter_id in self._subscribers:
                if filter_id is None or filter_id == player_id:
                    try:
                        q.put_nowait(payload)
                    except queue.Full:
                        pass  # drop slow clients
