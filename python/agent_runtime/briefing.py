"""Turn briefing generator - minimal announcement to start LLM turn."""
from __future__ import annotations

from typing import Any


def generate_turn_briefing(turn_number: int, blockers: list[dict[str, Any]] | None = None) -> str:
    """Generate turn announcement with blockers if present.

    The LLM should proactively query game state via tools (get_units, get_cities, etc.)
    rather than having it pre-fetched here. This follows the design philosophy that
    the LLM plays like a human: gathering info when needed, not waiting for briefings.

    Args:
        turn_number: Current turn number
        blockers: List of end-turn blockers from turn_start message
    """
    parts = [f"Turn {turn_number}."]

    if blockers:
        blocker_types = [b.get("type", "UNKNOWN") for b in blockers]
        parts.append(f"BLOCKERS to resolve before end_turn: {blocker_types}")
    else:
        parts.append("No blockers.")

    parts.append("Query game state and take your actions.")

    return " ".join(parts)

