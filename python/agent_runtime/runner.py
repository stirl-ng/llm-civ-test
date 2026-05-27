"""
Civ V LLM Agent Runner

Loop: subscribe to SSE turn events → call LLM with tools → execute tool calls → repeat until end_turn
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Windows cp1252 stdout breaks on Unicode chars; force UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
import yaml

from agent_runtime.context import TurnContext
from agent_runtime.http_client import check_health
from agent_runtime.models import get_model
from agent_runtime.turn_runner import run_turn
from agent_runtime.memory import get_journal

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


def make_halt_check(base_url: str):
    """Return a callable that polls the orchestrator for a halt signal."""
    def check() -> str | None:
        try:
            r = requests.get(f"{base_url}/observer/halt_status", timeout=2)
            if r.ok:
                data = r.json()
                if data.get("active"):
                    return data.get("reason", "Observer halt")
        except Exception:
            pass
        return None
    return check


def run_game_loop(
    model,
    base_url: str,
    turn_timeout: float | None = None,
    interactive: bool = False,
    temperature: float = 0.7,
):
    """Main loop: subscribe to SSE turn events, run each turn."""
    last_game_id = None

    try:
        while True:  # reconnect loop
            if not check_health(base_url):
                print("Waiting for orchestrator...")
                time.sleep(2)
                continue

            print("Connecting to event stream...")
            try:
                resp = requests.get(
                    f"{base_url}/events",
                    stream=True,
                    timeout=(10, None),
                )
                resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"SSE connect failed: {e}. Retrying in 2s...")
                time.sleep(2)
                continue

            print("Subscribed. Waiting for turns.")
            event_type = None

            try:
                for raw in resp.iter_lines(chunk_size=1):
                    line = raw.decode() if isinstance(raw, bytes) else raw
                    if not line:
                        event_type = None
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:") and event_type == "turn_start":
                        try:
                            event = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue

                        current_turn = event.get("turn")
                        current_game_id = event.get("game_id")
                        player_name = event.get("player_name")

                        if last_game_id is not None and current_game_id != last_game_id:
                            print(f"\nNEW GAME ({last_game_id} -> {current_game_id})")
                        last_game_id = current_game_id

                        if _message_logger:
                            _message_logger.set_turn(current_turn, current_game_id)

                        print(f"\n{'='*50}\nTURN {current_turn} (game_id: {current_game_id})\n{'='*50}")

                        ctx = TurnContext(
                            base_url=base_url,
                            turn=current_turn,
                            game_id=current_game_id,
                            player_name=player_name,
                            halt_check=make_halt_check(base_url),
                        )
                        result = run_turn(
                            model,
                            ctx,
                            timeout=turn_timeout,
                            interactive=interactive,
                            temperature=temperature,
                        )
                        print(f"\nSummary: {result['iterations']} iterations, {result['tool_calls']} tool calls")
                        if result.get("halted"):
                            print(f"\n{'='*50}\nHALTED: {result.get('reason')}\n{'='*50}")
                            return

            except KeyboardInterrupt:
                raise
            except requests.exceptions.RequestException as e:
                print(f"SSE stream lost: {e}. Reconnecting in 2s...")
                time.sleep(2)

    except KeyboardInterrupt:
        print("\nInterrupted")


def main():
    parser = argparse.ArgumentParser(description="Run Civ V LLM agent")
    parser.add_argument("--config", required=True, help="Config file or short name (e.g., 'gemini')")
    parser.add_argument("--interactive", action="store_true", help="Enable operator input")
    args = parser.parse_args()

    cfg = load_config(args.config)

    base_url = cfg.get("orchestrator", {}).get("url", "http://localhost:8765")
    model = get_model(cfg.get("backend", {}))

    journal = get_journal()
    player_id = journal.set_current_player(model.name())

    print(f"Model: {model.name()}")
    print(f"Player ID: {player_id}")
    print(f"Orchestrator: {base_url}")
    print()

    turn_timeout = cfg.get("orchestrator", {}).get("turn_timeout", None)
    interactive = cfg.get("orchestrator", {}).get("interactive", False)
    if args.interactive:
        interactive = True

    agent_cfg = cfg.get("agent", {})
    temperature = agent_cfg.get("temperature", 0.7)

    print(f"Connecting to {base_url}", end="", flush=True)
    while not check_health(base_url):
        print(".", end="", flush=True)
        time.sleep(1)
    print("  Connected!")

    print(f"Interactive: {interactive}")
    print(f"Temperature: {temperature}")

    run_game_loop(model, base_url, turn_timeout, interactive, temperature=temperature)


if __name__ == "__main__":
    main()
