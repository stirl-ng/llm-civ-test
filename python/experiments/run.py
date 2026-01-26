"""
Civ V LLM Experiment Runner

Uses native LLM tool calling (no regex parsing).
Loop: poll for turns → call LLM with tools → execute tool calls → repeat until end_turn
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import requests
import yaml

from agent_runtime.models import get_model
from agent_runtime.models.base import GenerateResponse, ToolCall
from agent_runtime.tools.schemas import get_openai_tools
from agent_runtime.prompts.system_prompt import build_system_prompt
from agent_runtime.briefing import generate_turn_briefing

# Optional: set turn on message logger for LLM response logging
try:
    from orchestrator.message_logger import get_message_logger
    _message_logger = get_message_logger()
except ImportError:
    _message_logger = None


def load_config(config_arg: str) -> dict[str, Any]:
    """Load config from path or short name (e.g., 'gemini' → configs/experiments/gemini.yaml)."""
    config_path = Path(config_arg)

    if not config_path.is_absolute() and "/" not in config_arg and "\\" not in config_arg:
        python_root = Path(__file__).resolve().parent.parent
        config_path = python_root / "configs" / "experiments" / f"{config_arg}.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# --- HTTP Helpers ---

def call_tool(base_url: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call an orchestrator tool via HTTP."""
    response = requests.post(
        f"{base_url}/tool",
        json={"tool": tool, "arguments": arguments},
        timeout=30.0
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


def get_status(base_url: str) -> dict[str, Any] | None:
    """Get current game status from orchestrator."""
    try:
        r = requests.get(f"{base_url}/status", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException:
        return None


# --- Tool Execution ---

def execute_tool(tool_call: ToolCall, base_url: str, turn: int) -> dict[str, Any]:
    """Execute a single tool call via orchestrator HTTP API.

    Args:
        tool_call: ToolCall object from model response
        base_url: Orchestrator base URL
        turn: Current turn number

    Returns:
        Tool result dict with 'ok' field and optional '_end_turn' flag
    """
    name = tool_call.name
    args = tool_call.arguments

    # Execute via orchestrator
    try:
        result = call_tool(base_url, name, args)
    except Exception as e:
        result = {"ok": False, "error": str(e)}

    # Mark end_turn and force_end_turn calls
    if name in ("end_turn", "force_end_turn"):
        result["_end_turn"] = True

    return result


# --- Message Building ---

def build_assistant_message(response: GenerateResponse) -> dict[str, Any]:
    """Build assistant message dict from model response.

    For OpenAI-style conversation history, assistant messages with tool calls
    need to include the tool_calls in a specific format.
    """
    msg: dict[str, Any] = {"role": "assistant", "content": response.text or None}

    if response.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                },
            }
            for tc in response.tool_calls
        ]

    return msg


def build_tool_result_message(tool_call: ToolCall, result: dict[str, Any]) -> dict[str, Any]:
    """Build tool result message for conversation history."""
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "content": json.dumps(result),
    }


# --- Core Turn Loop ---

def run_turn(model, base_url: str, turn: int, timeout: float | None = None) -> dict[str, Any]:
    """Run a single turn: LLM → execute tools → repeat until end_turn.

    Args:
        model: Model adapter instance
        base_url: Orchestrator base URL
        turn: Current turn number
        timeout: Optional timeout in seconds. None means no timeout.

    Returns:
        Dict with turn results
    """
    start_time = time.time()

    # Get tool schemas
    tools = get_openai_tools()

    # Build initial messages
    system_prompt = build_system_prompt()
    briefing = generate_turn_briefing(turn)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": briefing}
    ]

    iterations = 0
    tool_calls_total = 0

    print(f"  Starting turn {turn}...")

    # Tell logger about current turn
    if _message_logger:
        _message_logger.set_turn(turn)
        _message_logger.log({
            "type": "turn_start_messages",
            "system_prompt": system_prompt,
            "briefing": briefing,
        }, direction="outgoing")

    while True:
        # Check timeout
        if timeout is not None and time.time() - start_time >= timeout:
            print(f"  ⚠️  Turn timeout ({timeout}s)")
            break

        iterations += 1

        # Call LLM with tools
        try:
            response = model.generate(messages, tools=tools, temperature=0.2)
            preview = response.text[:150] + "..." if len(response.text) > 150 else response.text
            if preview:
                print(f"  [{iterations}] LLM: {preview}")
            if response.tool_calls:
                print(f"  [{iterations}] Tool calls: {[tc.name for tc in response.tool_calls]}")
        except Exception as e:
            print(f"  ✗ LLM error: {e}")
            break

        # Add assistant message to history
        messages.append(build_assistant_message(response))

        # No tool calls - check if we should prompt
        if not response.tool_calls:
            if iterations >= 3:
                print(f"  ⚠️  No tool calls after {iterations} iterations")
                break
            messages.append({"role": "user", "content": "Please call a tool or end_turn when ready."})
            continue

        # Execute each tool call
        for tool_call in response.tool_calls:
            tool_calls_total += 1

            try:
                result = execute_tool(tool_call, base_url, turn)
                is_ok = result.get("ok", True)
                print(f"    {'✓' if is_ok else '✗'} {tool_call.name}")

                # Add tool result to messages
                messages.append(build_tool_result_message(tool_call, result))

                # Check for end_turn
                if result.get("_end_turn"):
                    if not is_ok:
                        error = result.get("blocking_type") or result.get("message") or "blocked"
                        print(f"    ⚠️  end_turn blocked: {error}")
                        # Continue loop - model will see the error and try to fix
                    else:
                        # Wait for turn to actually advance
                        print(f"    ⏳ Waiting for turn to advance", end="", flush=True)
                        turn_advanced = False
                        for _ in range(20):  # Wait up to 10 seconds
                            print(".", end="", flush=True)
                            time.sleep(0.5)
                            status = get_status(base_url)
                            if status and status.get("turn") != turn:
                                turn_advanced = True
                                break

                        if turn_advanced:
                            print(f"  ✓ Turn {turn} ended")
                            return {"turn": turn, "iterations": iterations, "tool_calls": tool_calls_total, "success": True}
                        else:
                            print(f"    ⚠️  turn_end_ack received but turn didn't advance")
                            messages.append({
                                "role": "user",
                                "content": json.dumps({
                                    "error": "turn_not_advanced",
                                    "message": "end_turn was acknowledged but turn didn't advance. Something may still be blocking."
                                })
                            })

            except Exception as e:
                print(f"    ✗ {tool_call.name}: {e}")
                messages.append(build_tool_result_message(
                    tool_call,
                    {"ok": False, "error": str(e)}
                ))

    return {"turn": turn, "iterations": iterations, "tool_calls": tool_calls_total, "success": False}


def run_game_loop(model, base_url: str, poll_interval: float = 2.0, turn_timeout: float | None = None):
    """Main loop: poll for turns, run each turn.

    Args:
        model: Model adapter instance
        base_url: Orchestrator base URL
        poll_interval: Seconds between status polls
        turn_timeout: Optional timeout per turn in seconds
    """
    last_turn = None
    last_game_id = None

    try:
        while True:
            status = get_status(base_url)

            if not status or not status.get("connected"):
                time.sleep(poll_interval)
                continue

            current_turn = status.get("turn")
            current_game_id = status.get("game_id")

            # Check for new game
            if current_game_id is not None and last_game_id is not None and current_game_id != last_game_id:
                print(f"\n{'='*50}")
                print(f"🎮 NEW GAME DETECTED (game_id: {last_game_id} → {current_game_id})")
                print(f"{'='*50}")
                last_turn = None

            if current_game_id is not None:
                last_game_id = current_game_id

            # Skip if no new turn
            if current_turn is None or current_turn == last_turn:
                time.sleep(poll_interval)
                continue

            # New turn!
            print(f"\n{'='*50}")
            print(f"TURN {current_turn} (game_id: {current_game_id})")
            print(f"{'='*50}")

            if _message_logger:
                _message_logger.set_turn(current_turn, current_game_id)

            result = run_turn(model, base_url, current_turn, turn_timeout)

            print(f"\nSummary: {result['iterations']} iterations, {result['tool_calls']} tool calls")

            last_turn = current_turn
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nInterrupted")


def main():
    parser = argparse.ArgumentParser(description="Run Civ V LLM experiment")
    parser.add_argument("--config", required=True, help="Config file or short name (e.g., 'gemini')")
    args = parser.parse_args()

    cfg = load_config(args.config)

    # Build model
    base_url = cfg.get("orchestrator", {}).get("url", "http://localhost:8765")
    model = get_model(cfg.get("backend", {}))

    print(f"Model: {model.name()}")
    print(f"Orchestrator: {base_url}")
    print(f"Using native tool calling (no regex parsing)")
    print()

    poll_interval = cfg.get("orchestrator", {}).get("poll_interval", 2.0)
    turn_timeout = cfg.get("orchestrator", {}).get("turn_timeout", None)

    # Wait for orchestrator
    print(f"Connecting to {base_url}", end="", flush=True)
    while not check_health(base_url):
        print(".", end="", flush=True)
        time.sleep(1)
    print("  Connected!")

    run_game_loop(model, base_url, poll_interval, turn_timeout)


if __name__ == "__main__":
    main()
