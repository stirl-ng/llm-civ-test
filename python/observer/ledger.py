"""Parse JSONL game logs into structured per-turn records.

The ledger provides a clean view of what happened each turn:
- Which tools were called, in which iteration, and whether they succeeded
- What the LLM said at each step
- What the turn outcome was (success / blocked / timeout / incomplete)

All parsing is read-only and safe to run while the game is in progress.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_LOGS_DIR = Path(__file__).parent.parent / "logs"

# Fields in tool results that are too large to include in summaries
_LARGE_FIELDS = {"tiles", "map", "map_raw", "units", "cities", "available_techs"}


@dataclass
class ToolCallRecord:
    iteration: int
    tool: str
    arguments: dict[str, Any]
    result_summary: str
    ok: bool


@dataclass
class IterationRecord:
    iteration: int
    llm_text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass
class TurnRecord:
    turn: int
    game_id: int | None
    duration_seconds: float
    iterations: list[IterationRecord]
    blockers_at_start: list[dict]
    briefing: str
    outcome: str  # "success" | "blocked" | "timeout" | "incomplete"
    total_tool_calls: int
    total_errors: int
    error_tools: list[str]


def find_log_path(game_id: int, log_dir: Path | None = None) -> Path:
    base = log_dir or _LOGS_DIR
    return base / f"game_{game_id}.jsonl"


def result_summary(result: dict, max_len: int = 200) -> str:
    """Compact representation of a tool result, dropping large list fields."""
    slim = {k: v for k, v in result.items() if k not in _LARGE_FIELDS}
    # For large list fields, replace with a count hint
    for k in _LARGE_FIELDS:
        if k in result and isinstance(result[k], list):
            slim[f"{k}_count"] = len(result[k])
    text = json.dumps(slim, separators=(",", ":"))
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text


def parse_turn(messages: list[dict]) -> TurnRecord:
    """Build a TurnRecord from a pre-filtered list of messages for one turn."""
    turn_num = None
    game_id = None
    blockers_at_start: list[dict] = []
    briefing = ""
    start_time: datetime | None = None
    end_time: datetime | None = None

    # iteration_start messages give us clean boundaries
    # tool_result messages carry iteration numbers directly
    # llm_response messages are matched to the most recent iteration_start

    iterations_map: dict[int, IterationRecord] = {}
    current_iteration: int = 0
    end_turn_succeeded = False
    has_turn_complete = False

    def _parse_ts(ts: str | None) -> datetime | None:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    for msg in messages:
        mtype = msg.get("type")
        ts = _parse_ts(msg.get("timestamp"))

        if mtype == "turn_start":
            turn_num = msg.get("turn")
            game_id = msg.get("game_id")
            blockers_at_start = msg.get("blockers", [])
            start_time = ts

        elif mtype == "turn_start_messages":
            briefing = msg.get("briefing", "")

        elif mtype == "iteration_start":
            n = msg.get("iteration", current_iteration + 1)
            current_iteration = n
            if n not in iterations_map:
                iterations_map[n] = IterationRecord(iteration=n, llm_text="")

        elif mtype == "llm_response":
            # Associate with the current iteration
            n = current_iteration or 1
            if n not in iterations_map:
                iterations_map[n] = IterationRecord(iteration=n, llm_text="")
            iterations_map[n].llm_text = msg.get("response", "") or ""

        elif mtype == "tool_result":
            n = msg.get("iteration", current_iteration or 1)
            if n not in iterations_map:
                iterations_map[n] = IterationRecord(iteration=n, llm_text="")
            ok = msg.get("ok", True)
            tool = msg.get("tool", "?")
            rec = ToolCallRecord(
                iteration=n,
                tool=tool,
                arguments=msg.get("arguments", {}),
                result_summary=result_summary(msg.get("result", {})),
                ok=ok,
            )
            iterations_map[n].tool_calls.append(rec)
            if tool == "end_turn" and ok:
                end_turn_succeeded = True

        elif mtype == "turn_complete":
            has_turn_complete = True
            end_time = ts

    # Determine outcome
    if end_turn_succeeded:
        outcome = "success"
    elif has_turn_complete:
        outcome = "blocked"
    elif iterations_map:
        outcome = "incomplete"
    else:
        outcome = "incomplete"

    # Duration
    if start_time and end_time:
        duration = (end_time - start_time).total_seconds()
    else:
        duration = 0.0

    # Flatten iterations in order
    sorted_iters = [iterations_map[k] for k in sorted(iterations_map)]

    # Aggregate counts
    all_tool_calls = [tc for it in sorted_iters for tc in it.tool_calls]
    error_tools = [tc.tool for tc in all_tool_calls if not tc.ok]

    return TurnRecord(
        turn=turn_num or 0,
        game_id=game_id,
        duration_seconds=duration,
        iterations=sorted_iters,
        blockers_at_start=blockers_at_start,
        briefing=briefing,
        outcome=outcome,
        total_tool_calls=len(all_tool_calls),
        total_errors=len(error_tools),
        error_tools=error_tools,
    )


def parse_game_log(log_path: Path, since_turn: int = 0) -> list[TurnRecord]:
    """Parse a complete (or partial) JSONL game log into per-turn records."""
    by_turn: dict[int, list[dict]] = {}

    try:
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = msg.get("turn")
                if t is None:
                    continue
                if t < since_turn:
                    continue
                by_turn.setdefault(t, []).append(msg)
    except FileNotFoundError:
        return []

    return [parse_turn(msgs) for _, msgs in sorted(by_turn.items())]


def parse_turn_live(log_path: Path, turn: int, retries: int = 3, retry_delay: float = 0.5) -> TurnRecord | None:
    """Parse a single turn from a live (still-being-written) log.

    Retries a few times to allow the logger to flush the turn_complete line.
    Returns None if the turn hasn't started yet.
    """
    for attempt in range(retries):
        by_turn: dict[int, list[dict]] = {}
        try:
            with log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = msg.get("turn")
                    if t == turn:
                        by_turn.setdefault(t, []).append(msg)
        except FileNotFoundError:
            return None

        if turn not in by_turn:
            return None

        msgs = by_turn[turn]
        # Check if turn_complete has landed; if not, retry
        has_complete = any(m.get("type") == "turn_complete" for m in msgs)
        if has_complete or attempt == retries - 1:
            return parse_turn(msgs)

        time.sleep(retry_delay)

    return None
