from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class TurnContext:
    base_url: str
    turn: int
    game_id: int | None
    player_name: str | None = None
    halt_check: Callable[[], str | None] | None = None
