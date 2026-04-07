"""Turn briefing generator - Creates rich narrative context for each turn.

Philosophy:
- Each turn should feel like continuing a story, not starting a new task
- The LLM should know who it is, what's happened, and what it's been thinking
- Context creates continuity; continuity creates meaning
"""

from __future__ import annotations

from typing import Any, Optional

from .memory import get_journal


def _render_state_section(state: dict) -> str:
    """Render a compact Current State block from fetched game state."""
    lines = ["## Current State"]

    cities = state.get("cities") or []
    if cities:
        city_parts = []
        for c in cities:
            prod = c.get("production")
            prod_str = f"producing {prod['name']} ({prod['turns_left']} turns)" if prod else "idle"
            city_parts.append(f"{c['name']} (id={c['id']}) — {prod_str} — pop {c['population']}")
        lines.append("**Cities:** " + " | ".join(city_parts))

    units = state.get("units") or []
    if units:
        unit_parts = [f"{u['unit_type_name']} #{u['id']} at ({u['x']},{u['y']})" for u in units]
        lines.append("**Units:** " + " | ".join(unit_parts))

    research = state.get("current_research")
    available = state.get("available_techs") or []
    if research or available:
        res_str = f"{research['name']} ({research['turns_left']} turns left)" if research else "none"
        avail_str = ", ".join(t["name"] for t in available if not research or t["id"] != research.get("id"))
        lines.append(f"**Research:** {res_str}" + (f" | Available: {avail_str}" if avail_str else ""))

    return "\n".join(lines)


def generate_turn_briefing(
    turn_number: int,
    game_id: Optional[int] = None,
    player_name: Optional[str] = None,
    civ_name: Optional[str] = None,
    user_message: Optional[str] = None,
    state: Optional[dict] = None,
) -> str:
    """Generate a narrative turn briefing.

    This is the bridge between turns - it tells the LLM:
    1. Where we are in time (turn number)
    2. Who we are (identity from journal)
    3. What's happened recently (memories)
    4. What we've been thinking (our own reflections)

    Args:
        turn_number: Current turn number
        game_id: Game ID for journal lookup
        player_name: Leader name (for new games)
        civ_name: Civilization name (for new games)
        user_message: Optional message from the human operator
    """
    parts = []

    # Opening - situate in time
    if turn_number == 0:
        parts.append("**Dawn of a New Era**")
        parts.append("")
        parts.append("The world stretches before you, unknown and full of possibility.")
        parts.append("Your people look to you for guidance. Where will you lead them?")
        parts.append("")
        parts.append("*This is Turn 0. Your settler awaits your command to found your first city.*")
        parts.append("*Take a moment to look around (get_map_view), then found your capital.*")
    else:
        parts.append(f"**Turn {turn_number}**")
        parts.append("")

    # Journal context - who we are and what's happened
    if game_id is not None:
        journal = get_journal()
        context = journal.build_context_summary(game_id, turn_number)
        if context:
            parts.append(context)
            parts.append("")

    # Live game state - explicit IDs so the model doesn't need to look them up
    if state:
        parts.append(_render_state_section(state))
        parts.append("")

    # If this is a new game without journal context, note the fresh start
    if game_id is not None and turn_number == 0:
        journal = get_journal()
        narrative = journal.get_or_create_narrative(game_id)
        if not narrative.leader_name and player_name:
            journal.update_narrative(game_id, leader_name=player_name, civ_name=civ_name)

    # Gentle guidance (not commands)
    if turn_number == 0:
        pass  # Already gave guidance above
    elif turn_number < 10:
        parts.append("*Early game. Focus on exploration and establishing your foundation.*")
    elif turn_number % 25 == 0:
        parts.append("*A milestone turn. Perhaps a good time to reflect on your strategy.*")

    # Human operator message
    if user_message:
        parts.append("")
        parts.append(f"**Message from beyond:** {user_message}")

    # Closing - invitation to engage
    parts.append("")
    if turn_number == 0:
        parts.append("What kind of leader will you be? The choice is yours.")
    else:
        parts.append("What will you do?")

    return "\n".join(parts)


def generate_reflection_prompt(turn_number: int) -> str:
    """Generate a prompt asking the LLM to reflect on the turn.

    Called at the end of a turn before end_turn, asking the LLM
    to record its thoughts for future continuity.
    """
    return (
        f"Before ending turn {turn_number}, reflect briefly:\n"
        "1. Call `record_recap` with 2-4 sentences on what happened and what you're planning.\n"
        "2. Call `update_strategy` if your strategy has changed.\n"
        "3. Call `record_lesson` if you learned something that applies beyond this game.\n"
        "Then call `end_turn` again."
    )


def generate_game_start_prompt(leader_name: str, civ_name: str, personality_desc: str) -> str:
    """Generate the opening narrative for a new game.

    This establishes who the LLM is and invites them into the experience.
    """
    return f"""# The Beginning

You are **{leader_name}**, leader of **{civ_name}**.

{personality_desc}

---

The year is 4000 BC. Your people have wandered long enough. They look to you now,
their chosen leader, to find a home and build something that will last.

A settler party awaits your command. Scouts report this land has potential -
but so much remains unknown. Mountains on the horizon. Rivers glinting in the distance.
And somewhere out there, perhaps, others like you with their own dreams of empire.

This is your story. How will it unfold?

---

*Take a moment to survey your surroundings with get_map_view before founding your capital.*
*Consider what kind of civilization you want to build.*
"""
