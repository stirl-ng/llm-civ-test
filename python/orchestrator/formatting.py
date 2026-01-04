"""Game state formatting utilities for debug output."""

from __future__ import annotations

import json
from typing import Any


def format_game_state(data: dict[str, Any]) -> str:
    """Format game state data for human-readable display.

    Handles both:
    - Full message: {'type': 'turn_start', 'turn': 7, 'state': {...}}
    - Just state: {'turn': 7, 'playersAlive': 18, ...}
    """
    lines = []

    # Check if this is a full message or just state
    msg_type = data.get("type", "")

    if msg_type == "turn_start":
        # Full turn_start message
        turn = data.get("turn", "?")
        player_id = data.get("player_id", "?")
        state = data.get("state", {})

        lines.append("=" * 60)
        lines.append(f"TURN {turn} - Player {player_id}")
        lines.append("=" * 60)

        # Format state contents
        lines.append(f"  Players Alive: {state.get('playersAlive', '?')}")
        lines.append(f"  Civs Ever:     {state.get('civsEver', '?')}")

        # Add any other state fields
        for key, value in state.items():
            if key not in ('turn', 'playersAlive', 'civsEver'):
                if isinstance(value, (dict, list)):
                    lines.append(f"  {key}: {json.dumps(value, indent=4)}")
                else:
                    lines.append(f"  {key}: {value}")

        lines.append("=" * 60)

    elif "turn" in data and "playersAlive" in data:
        # Just the inner state object
        lines.append("=" * 60)
        lines.append("GAME STATE")
        lines.append("=" * 60)
        lines.append(f"  Turn:          {data.get('turn', '?')}")
        lines.append(f"  Players Alive: {data.get('playersAlive', '?')}")
        lines.append(f"  Civs Ever:     {data.get('civsEver', '?')}")

        for key, value in data.items():
            if key not in ('turn', 'playersAlive', 'civsEver'):
                if isinstance(value, (dict, list)):
                    lines.append(f"  {key}: {json.dumps(value, indent=4)}")
                else:
                    lines.append(f"  {key}: {value}")

        lines.append("=" * 60)

    else:
        # Unknown format, just pretty-print
        lines.append(f"Message (type={msg_type or 'unknown'}):")
        lines.append(json.dumps(data, indent=2))

    return "\n".join(lines)


def format_message(raw: str, raw_mode: bool = False) -> str:
    """Parse and format a raw JSON message.

    Args:
        raw: Raw JSON string
        raw_mode: If True, return the raw JSON; if False, format nicely

    Returns:
        Formatted string for display
    """
    if raw_mode:
        return raw
    try:
        data = json.loads(raw)
        return format_game_state(data)
    except json.JSONDecodeError as e:
        return f"[warn] Invalid JSON: {e}\n  Raw: {raw[:200]}..."
