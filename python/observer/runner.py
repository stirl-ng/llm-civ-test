"""Observer runner: watch a live game, analyze each turn, halt if needed.

Mirrors agent_runtime/runner.py's SSE subscription pattern but listens for
turn_complete events and calls a second LLM for analysis instead of playing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
import yaml

from observer.ledger import find_log_path, parse_turn_live, parse_game_log, TurnRecord
from observer.prompts import build_turn_analysis_prompt, build_game_recommendations_prompt

_LOGS_DIR = Path(__file__).parent.parent / "logs"


def load_config(config_arg: str) -> dict[str, Any]:
    config_path = Path(config_arg)
    if not config_path.is_absolute() and "/" not in config_arg and "\\" not in config_arg:
        python_root = Path(__file__).resolve().parent.parent
        # Check configs/observer/ first, then configs/experiments/ as fallback
        for subdir in ("observer", "experiments"):
            candidate = python_root / "configs" / subdir / f"{config_arg}.yaml"
            if candidate.exists():
                config_path = candidate
                break
        else:
            config_path = python_root / "configs" / "observer" / f"{config_arg}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _post_halt(base_url: str, reason: str, game_id: int | None, turn: int) -> None:
    try:
        requests.post(
            f"{base_url}/observer/halt",
            json={"reason": reason, "game_id": game_id, "turn": turn},
            timeout=5,
        )
    except Exception as e:
        print(f"  [observer] Warning: failed to post halt signal: {e}")


def _write_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _check_halt_in_response(text: str) -> str | None:
    """Parse the halt decision from the observer LLM's response.

    Looks for a line that starts with YES (case-insensitive) in the halt
    decision section. Returns the halt reason if found, None otherwise.
    """
    in_halt_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if "halt decision" in stripped.lower():
            in_halt_section = True
            continue
        if in_halt_section and stripped:
            if stripped.upper().startswith("YES"):
                # The reason is on the next non-empty line, or after "YES:"
                rest = stripped[3:].lstrip(":").strip()
                return rest or "Observer flagged critical issue (see analysis)"
            if stripped.upper().startswith("NO"):
                return None
    return None


def run_observer_loop(
    model,
    base_url: str,
    log_dir: Path | None = None,
    output_log: Path | None = None,
    since_turn: int = 0,
    temperature: float = 0.3,
) -> None:
    log_dir = log_dir or _LOGS_DIR
    current_game_id: int | None = None
    per_turn_observations: list[str] = []
    turn_records: list[TurnRecord] = []
    game_summary = ""

    def get_output_log(gid: int | None) -> Path:
        if output_log:
            return output_log
        return _LOGS_DIR / f"observer_{gid or 'unknown'}.jsonl"

    def _generate_game_recommendations(gid: int | None) -> None:
        if not turn_records:
            print("[observer] No turns recorded — skipping end-of-game summary.")
            return
        print(f"\n[observer] Generating end-of-game recommendations ({len(turn_records)} turns)...")
        prompt = build_game_recommendations_prompt(turn_records, per_turn_observations, gid)
        try:
            analysis = model.generate_text(
                [
                    {"role": "system", "content": "You are an expert game AI evaluator analyzing a Civilization V LLM agent's play session."},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
        except Exception as e:
            print(f"[observer] Error generating recommendations: {e}")
            return

        print("\n" + "="*60)
        print("END-OF-GAME RECOMMENDATIONS")
        print("="*60)
        print(analysis)
        print("="*60 + "\n")

        _write_jsonl(get_output_log(gid), {
            "type": "observer_game_summary",
            "game_id": gid,
            "turns_observed": len(turn_records),
            "analysis": analysis,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    try:
        while True:  # reconnect loop
            try:
                resp = requests.get(f"{base_url}/health", timeout=5)
                resp.raise_for_status()
            except Exception:
                print("[observer] Waiting for orchestrator...")
                time.sleep(2)
                continue

            print("[observer] Connecting to event stream...")
            try:
                resp = requests.get(f"{base_url}/events", stream=True, timeout=(10, None))
                resp.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"[observer] SSE connect failed: {e}. Retrying in 2s...")
                time.sleep(2)
                continue

            print("[observer] Subscribed. Waiting for turn_complete events.")
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
                    elif line.startswith("data:"):
                        try:
                            event = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue

                        if event_type == "disconnected":
                            print("[observer] Orchestrator disconnected.")
                            _generate_game_recommendations(current_game_id)
                            return

                        if event_type != "turn_complete":
                            continue

                        turn_num = event.get("turn")
                        game_id = event.get("game_id")

                        if game_id and game_id != current_game_id:
                            if current_game_id is not None:
                                print(f"[observer] New game detected ({current_game_id} → {game_id})")
                                _generate_game_recommendations(current_game_id)
                                per_turn_observations.clear()
                                turn_records.clear()
                                game_summary = ""
                            current_game_id = game_id

                        if turn_num is None or turn_num < since_turn:
                            continue

                        log_path = find_log_path(current_game_id, log_dir)
                        print(f"[observer] Turn {turn_num} complete — reading ledger...")
                        record = parse_turn_live(log_path, turn_num)
                        if record is None:
                            print(f"[observer] Warning: could not parse turn {turn_num} from log")
                            continue

                        turn_records.append(record)

                        prompt = build_turn_analysis_prompt(record, game_summary)
                        try:
                            analysis = model.generate_text(
                                [
                                    {"role": "system", "content": "You are an expert game AI evaluator watching a Civilization V LLM agent play in real time."},
                                    {"role": "user", "content": prompt},
                                ],
                                temperature=temperature,
                            )
                        except Exception as e:
                            print(f"[observer] Error analyzing turn {turn_num}: {e}")
                            continue

                        per_turn_observations.append(analysis)

                        # Update rolling game summary (one sentence per turn)
                        outcome_line = f"Turn {turn_num}: {record.outcome} ({record.total_tool_calls} calls, {record.total_errors} errors)"
                        game_summary = (game_summary + "\n" + outcome_line).strip()

                        print(f"\n[observer] Turn {turn_num} analysis:")
                        print(analysis)

                        _write_jsonl(get_output_log(current_game_id), {
                            "type": "observer_turn",
                            "turn": turn_num,
                            "game_id": current_game_id,
                            "outcome": record.outcome,
                            "observation": analysis,
                            "halted": False,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        })

                        # Check halt decision
                        halt_reason = _check_halt_in_response(analysis)
                        if halt_reason:
                            print(f"\n{'!'*60}")
                            print(f"OBSERVER HALT — Turn {turn_num}: {halt_reason}")
                            print(f"{'!'*60}\n")
                            _write_jsonl(get_output_log(current_game_id), {
                                "type": "observer_turn",
                                "turn": turn_num,
                                "game_id": current_game_id,
                                "outcome": record.outcome,
                                "observation": analysis,
                                "halted": True,
                                "halt_reason": halt_reason,
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            })
                            _post_halt(base_url, halt_reason, current_game_id, turn_num)

            except KeyboardInterrupt:
                raise
            except requests.exceptions.RequestException as e:
                print(f"[observer] SSE stream lost: {e}. Reconnecting in 2s...")
                time.sleep(2)

    except KeyboardInterrupt:
        print("\n[observer] Interrupted")
        _generate_game_recommendations(current_game_id)


def run_post_game(
    model,
    game_id: int,
    log_dir: Path | None = None,
    output_log: Path | None = None,
    since_turn: int = 0,
    temperature: float = 0.3,
) -> None:
    """Analyze a completed game log offline."""
    log_dir = log_dir or _LOGS_DIR
    out = output_log or (_LOGS_DIR / f"observer_{game_id}.jsonl")

    log_path = find_log_path(game_id, log_dir)
    print(f"[observer] Parsing {log_path}...")
    records = parse_game_log(log_path, since_turn=since_turn)
    if not records:
        print("[observer] No turns found in log.")
        return

    print(f"[observer] Analyzing {len(records)} turns...")
    per_turn_observations: list[str] = []
    game_summary = ""

    for record in records:
        prompt = build_turn_analysis_prompt(record, game_summary)
        try:
            analysis = model.generate_text(
                [
                    {"role": "system", "content": "You are an expert game AI evaluator analyzing a completed Civilization V LLM agent session."},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
        except Exception as e:
            print(f"[observer] Error on turn {record.turn}: {e}")
            analysis = f"(error: {e})"

        per_turn_observations.append(analysis)
        game_summary = (game_summary + f"\nTurn {record.turn}: {record.outcome}").strip()
        print(f"  Turn {record.turn}: {record.outcome}")

        _write_jsonl(out, {
            "type": "observer_turn",
            "turn": record.turn,
            "game_id": game_id,
            "outcome": record.outcome,
            "observation": analysis,
            "halted": False,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    prompt = build_game_recommendations_prompt(records, per_turn_observations, game_id)
    try:
        summary = model.generate_text(
            [
                {"role": "system", "content": "You are an expert game AI evaluator analyzing a completed Civilization V LLM agent session."},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
    except Exception as e:
        summary = f"(error generating summary: {e})"

    print("\n" + "="*60)
    print("RECOMMENDATIONS")
    print("="*60)
    print(summary)

    _write_jsonl(out, {
        "type": "observer_game_summary",
        "game_id": game_id,
        "turns_observed": len(records),
        "analysis": summary,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    print(f"\n[observer] Written to {out}")


def main():
    parser = argparse.ArgumentParser(description="Run Civ V LLM observer")
    parser.add_argument("--config", required=True, help="Config file or short name (e.g., 'observer')")
    parser.add_argument("--post-game", type=int, metavar="GAME_ID", help="Analyze a completed log offline")
    parser.add_argument("--since-turn", type=int, default=0)
    args = parser.parse_args()

    cfg = load_config(args.config)

    from agent_runtime.models import get_model
    model = get_model(cfg.get("backend", {}))

    obs_cfg = cfg.get("observer", {})
    base_url = obs_cfg.get("orchestrator_url", "http://localhost:8765")
    temperature = obs_cfg.get("temperature", 0.3)
    since_turn = args.since_turn or obs_cfg.get("since_turn", 0)
    log_dir_str = obs_cfg.get("log_dir")
    log_dir = Path(log_dir_str) if log_dir_str else None
    output_log_str = obs_cfg.get("output_log")
    output_log = Path(output_log_str) if output_log_str else None

    print(f"Observer model: {model.name()}")
    print(f"Temperature: {temperature}")

    if args.post_game:
        run_post_game(model, args.post_game, log_dir, output_log, since_turn, temperature)
    else:
        print(f"Watching: {base_url}")
        run_observer_loop(model, base_url, log_dir, output_log, since_turn, temperature)


if __name__ == "__main__":
    main()
