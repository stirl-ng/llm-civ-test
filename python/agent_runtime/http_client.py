from __future__ import annotations

from typing import Any

import requests


def call_tool(base_url: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call an orchestrator tool via HTTP."""
    response = requests.post(
        f"{base_url}/tool",
        json={"tool": tool, "arguments": arguments},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


def check_health(base_url: str) -> bool:
    """Check if orchestrator is running."""
    try:
        r = requests.get(f"{base_url}/health", timeout=5.0)
        return r.ok and r.json().get("status") == "ok"
    except requests.exceptions.RequestException:
        return False


def fetch_notifications(base_url: str, since_turn: int) -> list[dict[str, Any]]:
    """Fetch notifications for the current turn (used for mid-turn injection)."""
    try:
        r = requests.get(f"{base_url}/notifications", params={"since_turn": since_turn}, timeout=3.0)
        if r.ok:
            return r.json().get("notifications", [])
    except requests.exceptions.RequestException:
        pass
    return []


def fetch_turn_state(base_url: str) -> dict[str, Any]:
    """Fetch live game state at turn start for briefing enrichment.

    Returns partial state on failure — missing keys are simply omitted from the briefing.
    """
    state: dict[str, Any] = {}
    for tool, key in (("get_cities", "cities"), ("get_units", "units"), ("get_available_techs", None)):
        try:
            result = call_tool(base_url, tool, {})
            if result.get("ok"):
                if key == "cities":
                    state["cities"] = result.get("cities", [])
                elif key == "units":
                    state["units"] = result.get("units", [])
                else:
                    state["current_research"] = result.get("current_research")
                    state["available_techs"] = result.get("available_techs", [])
        except Exception:
            pass
    return state
