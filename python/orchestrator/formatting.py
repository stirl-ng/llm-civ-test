"""Game state formatting utilities for debug output."""

from __future__ import annotations

import json
from typing import Any


def format_game_state(data: dict[str, Any]) -> str:
    """Format game state data for human-readable display."""
    lines = []

    kind = data.get("kind", "unknown")
    category = data.get("category", "")

    if kind == "state" and category == "game_level":
        game_data = data.get("data", {})
        lines.append("=" * 60)
        lines.append("GAME LEVEL STATE")
        lines.append("=" * 60)
        lines.append(f"  Turn:        {game_data.get('turn', '?')}")
        lines.append(f"  Game Speed:  {game_data.get('game_speed', '?')}")
        lines.append(f"  Difficulty:  {game_data.get('difficulty', '?')}")
        lines.append(f"  Era:         {game_data.get('era', '?')}")
        lines.append(f"  Map Size:    {game_data.get('map_size', '?')}")
        lines.append(f"  Map Type:    {game_data.get('map_type', '?')}")
        lines.append(f"  Sea Level:   {game_data.get('sea_level', '?')}")
        lines.append(f"  Players:     {game_data.get('players_alive', '?')} alive / {game_data.get('civs_ever', '?')} ever")

        victory_conds = game_data.get("victory_conditions", [])
        if victory_conds:
            lines.append(f"  Victory:     {', '.join(victory_conds)}")

        victory_progress = game_data.get("victory_progress", {})
        if victory_progress:
            lines.append("")
            lines.append("  Victory Progress:")
            for vtype, vprog in victory_progress.items():
                if isinstance(vprog, dict):
                    prog_str = ", ".join(f"{k}={v}" for k, v in vprog.items())
                    lines.append(f"    {vtype}: {prog_str}")

        lines.append("=" * 60)
    else:
        # Unknown format, just pretty-print
        lines.append(f"Received {kind} message:")
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
