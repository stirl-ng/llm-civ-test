"""Simple web dashboard for debugging LLM Civ V runs.

Reads from JSONL logs and displays:
- Full LLM conversation organized by turn
- Tool calls with pass/fail status
- Token usage stats

Run: python -m orchestrator.dashboard
Add ?debug=1 to URL to see parse diagnostics
"""

import json
import logging
import queue
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Windows cp1252 stdout breaks on Unicode chars; force UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import time as _time

from flask import Flask, Response, render_template, request

_broadcaster = None

# Per-game message cache so SSE pushes don't re-read the full JSONL each time.
# Keyed by game_id; stores file size at last read + parsed messages + error count.
_msg_cache: dict[int, dict] = {}
_cnt_cache: dict[int, dict] = {}  # game_id -> {mtime, count}


def _read_messages(log_file: Path, game_id: int) -> tuple[list, int]:
    """Read JSONL messages incrementally (only new bytes since last call)."""
    size = log_file.stat().st_size
    cached = _msg_cache.get(game_id)
    if cached and cached["size"] == size:
        return cached["messages"], cached["errors"]

    prior_size   = cached["size"]     if cached else 0
    prior_msgs   = list(cached["messages"]) if cached else []
    prior_errors = cached["errors"]   if cached else 0

    new_msgs = []
    new_errors = 0
    with open(log_file, "r", encoding="utf-8") as f:
        if prior_size:
            f.seek(prior_size)
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                new_msgs.append(json.loads(stripped))
            except json.JSONDecodeError:
                new_errors += 1

    all_msgs   = prior_msgs + new_msgs
    all_errors = prior_errors + new_errors
    _msg_cache[game_id] = {"size": size, "messages": all_msgs, "errors": all_errors}
    return all_msgs, all_errors


def _count_messages(file_path: Path, game_id: int) -> int:
    """Count non-empty lines, cached by mtime."""
    mtime = file_path.stat().st_mtime
    cached = _cnt_cache.get(game_id)
    if cached and cached["mtime"] == mtime:
        return cached["count"]
    count = sum(1 for line in open(file_path, "r", encoding="utf-8") if line.strip())
    _cnt_cache[game_id] = {"mtime": mtime, "count": count}
    return count


def init(broadcaster) -> None:
    """Connect dashboard to the orchestrator's EventBroadcaster for live push updates."""
    global _broadcaster
    _broadcaster = broadcaster

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent
app = Flask(__name__, template_folder=str(TEMPLATE_DIR))

LOG_DIR = Path(__file__).parent.parent / "logs"



@dataclass
class DebugInfo:
    """Diagnostic information about log parsing."""
    log_file_name: str = ""
    file_exists: bool = False
    total_lines: int = 0
    empty_lines: int = 0
    parse_errors: int = 0
    type_counts: dict = field(default_factory=dict)
    unrecognized_types: list = field(default_factory=list)
    conversation_before_limit: int = 0
    conversation_after_limit: int = 0
    tools_before_limit: int = 0
    tools_after_limit: int = 0
    events_before_limit: int = 0
    events_after_limit: int = 0
    notifs_before_limit: int = 0
    notifs_after_limit: int = 0


# Known message types we process
KNOWN_TYPES = {
    "turn_start_messages",
    "llm_request",
    "llm_response",
    "tool_request",
    "tool_response",
    "notification",
    "turn_start",
    "turn_complete",
    "heartbeat",
    "popup_choice_needed",
    "command_response",
    "game_start",
    # Tool command types (sent to DLL)
    "get_units",
    "get_cities",
    "get_city_production",
    "get_available_techs",
    "get_available_policies",
    "move_unit",
    "unit_found_city",
    "unit_sleep",
    "unit_skip",
    "set_city_production",
    "send_action",
    "end_turn",
    "force_end_turn",
    # Map visualization tools
    "get_visible_tiles",
    "get_map_view",
    "get_unit_build_options",
    "get_reachable_tiles",
}

# Query tools (read-only information gathering)
QUERY_TOOLS = {
    "get_units",
    "get_cities",
    "get_city_production",
    "get_available_techs",
    "get_available_policies",
    "get_turn_blockers",
    "get_notifications",
    # Map visualization tools
    "get_visible_tiles",
    "get_map_view",
    "get_unit_build_options",
    "get_reachable_tiles",
}

# Action tools (modify game state)
ACTION_TOOLS = {
    "move_unit",
    "unit_found_city",
    "unit_sleep",
    "unit_skip",
    "set_city_production",
    "choose_tech",
    "adopt_policy",
    "send_action",
    "end_turn",
}


def filter_tool_calls_from_text(text: str) -> str:
    """Remove mcp_call() and other tool invocation lines from text.

    This filters out lines like:
    - mcp_call(tool="...", arguments={...})
    - end_turn(turn=N)
    - Other tool-related syntax

    We want to show only the LLM's reasoning and natural language responses,
    since tool calls are already visualized in the Tool Activity panel.
    """
    if not text:
        return text

    lines = text.split('\n')
    filtered_lines = []

    # Tool patterns to filter out
    tool_patterns = [
        "mcp_call(",
        "end_turn(",
        "send_action(",
        "move_unit(",
        "unit_found_city(",
        "unit_sleep(",
        "unit_skip(",
        "set_city_production(",
        "choose_tech(",
        "adopt_policy(",
        "get_units(",
        "get_cities(",
        "get_city_production(",
        "get_available_techs(",
        "get_available_policies(",
        "get_turn_blockers(",
        "get_notifications(",
        "force_end_turn(",
        # Map visualization tools
        "get_visible_tiles(",
        "get_map_view(",
        "get_unit_build_options(",
        "get_reachable_tiles(",
    ]

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            filtered_lines.append(line)
            continue

        # Skip lines that match tool call patterns
        is_tool_call = any(stripped.startswith(pattern) for pattern in tool_patterns)
        if is_tool_call:
            continue

        filtered_lines.append(line)

    result = '\n'.join(filtered_lines).strip()

    # Clean up excessive blank lines (more than 2 consecutive)
    while '\n\n\n' in result:
        result = result.replace('\n\n\n', '\n\n')

    return result


def parse_logs(debug_mode: bool = False, game_id: int | None = None) -> dict[str, Any]:
    """Parse JSONL logs and build conversation + tool call list.

    Args:
        debug_mode: Show debug diagnostics panel
        game_id: Filter to specific game_id (None = auto-select most recent)
    """
    debug = DebugInfo()
    debug.type_counts = defaultdict(int)

    data = {
        "connected": False,
        "current_turn": None,
        "total_tokens": 0,
        "total_requests": 0,
        "estimated_cost": 0.0,
        "conversation": [],
        "tool_calls": [],
        "game_events": [],
        "notifications": [],
        "last_update": datetime.now().strftime("%H:%M:%S"),
        "debug_mode": debug_mode,
        "debug": {},
        "game_id": game_id,
        "available_games": [],
    }

    # Scan for game_*.jsonl files in the logs directory
    if not LOG_DIR.exists():
        logger.warning(f"Log directory not found: {LOG_DIR}")
        if debug_mode:
            debug.log_file_name = "(no log dir)"
            debug.file_exists = False
            data["debug"] = debug.__dict__
        return data

    game_files = list(LOG_DIR.glob("game_*.jsonl"))
    if not game_files:
        logger.info("No game log files found in logs directory")
        if debug_mode:
            debug.log_file_name = "(no game files)"
            debug.file_exists = False
            data["debug"] = debug.__dict__
        return data

    # Extract game_ids from filenames and sort by modification time (most recent first)
    game_info = []
    for file_path in game_files:
        try:
            # Extract game_id from filename: game_12345.jsonl -> 12345
            gid = int(file_path.stem.split("_")[1])
            mtime = file_path.stat().st_mtime
            game_info.append((gid, file_path, mtime))
        except (ValueError, IndexError):
            logger.warning(f"Skipping malformed game file: {file_path.name}")
            continue

    if not game_info:
        logger.warning("No valid game files found")
        if debug_mode:
            debug.log_file_name = "(no valid files)"
            debug.file_exists = False
            data["debug"] = debug.__dict__
        return data

    # Sort by mtime (most recent first)
    game_info.sort(key=lambda x: x[2], reverse=True)

    # Auto-select most recent game if not specified
    if game_id is None:
        game_id = game_info[0][0]
        logger.info(f"Auto-selected most recent game_id: {game_id}")

    # Find the log file for selected game
    log_file = None
    for gid, file_path, _ in game_info:
        if gid == game_id:
            log_file = file_path
            break

    if log_file is None:
        logger.warning(f"Game {game_id} not found in logs")
        if debug_mode:
            debug.log_file_name = f"game_{game_id}.jsonl (not found)"
            debug.file_exists = False
            data["debug"] = debug.__dict__
        return data

    # Update debug info
    debug.log_file_name = log_file.name
    debug.file_exists = log_file.exists()
    data["game_id"] = game_id

    # Parse all messages from selected game file (incremental: only reads new bytes)
    messages, parse_errors = _read_messages(log_file, game_id)
    debug.total_lines = len(messages)
    debug.parse_errors = parse_errors
    if parse_errors:
        logger.warning(f"Cumulative JSON parse errors for game {game_id}: {parse_errors}")
    for msg in messages:
        msg_type = msg.get("type", "(no type)")
        debug.type_counts[msg_type] += 1

    # Build list of available games from scanned files
    available_games = []
    for gid, file_path, mtime in game_info:
        # Count messages in this game file (only for display)
        msg_count = _count_messages(file_path, gid)
        available_games.append({
            "game_id": gid,
            "message_count": msg_count,
            "is_current": gid == game_id,
        })
    data["available_games"] = available_games

    # Find unrecognized types
    for t in debug.type_counts:
        if t not in KNOWN_TYPES and t != "(no type)":
            debug.unrecognized_types.append(f"{t} ({debug.type_counts[t]})")

    if debug.parse_errors > 0:
        logger.warning(f"Found {debug.parse_errors} JSON parse errors in log file")

    if not messages:
        logger.info("Log file exists but contains no valid messages")
        if debug_mode:
            data["debug"] = debug.__dict__
        return data

    logger.info(f"Parsed {len(messages)} messages from {debug.total_lines} lines")

    # Get connection status and current turn
    for msg in reversed(messages):
        if msg.get("game_id"):
            data["connected"] = True
            break

    for msg in reversed(messages):
        if msg.get("turn") is not None:
            data["current_turn"] = msg["turn"]
            break

    # Build conversation, tool calls, notifications, and game events
    conversation = []
    tool_calls = []
    game_events = []
    notifications = []
    seen_turns = set()
    last_turn = None

    # Track tool requests to pair with responses
    pending_tools = {}  # uuid -> tool_name

    for msg in messages:
        msg_type = msg.get("type", "")
        turn = msg.get("turn")

        # Add turn divider when turn changes
        if turn is not None and turn != last_turn:
            if turn not in seen_turns:
                conversation.append({
                    "type": "turn_divider",
                    "turn": turn,
                    "role": "",
                    "content": "",
                })
                seen_turns.add(turn)
            last_turn = turn

        # === CONVERSATION MESSAGES ===

        # Turn start - system prompt + briefing
        if msg_type == "turn_start_messages":
            system_prompt = msg.get("system_prompt", "")
            briefing = msg.get("briefing", "")

            if system_prompt:
                conversation.append({
                    "type": "message",
                    "role": "system",
                    "content": system_prompt,
                    "turn": turn or 0,
                    "tokens": 0,
                })

            if briefing:
                conversation.append({
                    "type": "message",
                    "role": "user",
                    "content": briefing,
                    "turn": turn or 0,
                    "tokens": 0,
                })

        # LLM request - shows what was sent to the LLM
        if msg_type == "llm_request":
            uuid = msg.get("uuid")
            latest = msg.get("latest_message", {})
            role = latest.get("role", "user")
            content = latest.get("content", "")

            if content:
                # Truncate very long content for display
                display_content = content if len(content) < 2000 else content[:2000] + "\n\n[... truncated ...]"
                conversation.append({
                    "type": "message",
                    "role": role,
                    "content": display_content,
                    "turn": turn or 0,
                    "tokens": 0,
                })
            data["total_requests"] += 1

        # LLM response - shows what came back
        if msg_type == "llm_response":
            response = msg.get("response", "")
            thinking = msg.get("thinking_text", "")
            tokens = msg.get("total_tokens", 0) or 0

            if thinking:
                conversation.append({
                    "type": "message",
                    "role": "thinking",
                    "content": thinking,
                    "turn": turn or 0,
                    "tokens": 0,
                })

            if response:
                # Filter out tool call syntax - those are shown in Tool Activity panel
                filtered_response = filter_tool_calls_from_text(response)

                # Only add to conversation if there's meaningful content after filtering
                if filtered_response:
                    conversation.append({
                        "type": "message",
                        "role": "assistant",
                        "content": filtered_response,
                        "turn": turn or 0,
                        "tokens": tokens,
                    })

            data["total_tokens"] += tokens

        # === TOOL ACTIVITY ===

        # Tool request - orchestrator is about to call a tool
        if msg_type == "tool_request":
            tool_name = msg.get("tool", "?")
            uuid = msg.get("uuid")
            pending_tools[uuid] = tool_name

        # Tool response - result from DLL
        if msg_type == "tool_response":
            tool_name = msg.get("tool", "?")
            result = msg.get("result", {})
            arguments = msg.get("arguments", {})

            # Determine if query or action
            category = "query" if tool_name in QUERY_TOOLS else "action"
            icon = "🔍" if category == "query" else "⚡"

            # Check various error indicators
            is_ok = result.get("ok", True)
            if result.get("type") == "error" or result.get("status") == "error" or result.get("error"):
                is_ok = False
                icon = "✗"

            # Generate result summary
            result_summary = ""
            if not is_ok:
                # Handle various error formats
                error_msg = result.get("message")
                if not error_msg:
                    error_field = result.get("error")
                    if isinstance(error_field, dict):
                        error_msg = error_field.get("message", "Unknown error")
                    elif isinstance(error_field, str):
                        error_msg = error_field
                    else:
                        error_msg = "Unknown error"
                result_summary = f"Error: {error_msg}"
            elif category == "action":
                # For actions, show what happened
                if result.get("success"):
                    if tool_name == "move_unit":
                        result_summary = "Unit moved"
                    elif tool_name == "unit_found_city":
                        result_summary = "City founded"
                    elif tool_name == "set_city_production":
                        item_name = result.get("item_name", "?")
                        result_summary = f"Building: {item_name}"
                    elif tool_name == "send_action":
                        action_type = result.get("type", "?")
                        result_summary = f"{action_type.replace('_', ' ').title()}"
                    elif tool_name == "end_turn":
                        result_summary = "Turn ended"
                    else:
                        result_summary = "Success"
            else:
                # For queries, show data summary
                if tool_name == "get_units":
                    units = result.get("units", [])
                    result_summary = f"{len(units)} unit(s)"
                elif tool_name == "get_cities":
                    cities = result.get("cities", [])
                    result_summary = f"{len(cities)} city/cities"
                elif tool_name == "get_available_techs":
                    techs = result.get("available_techs", [])
                    result_summary = f"{len(techs)} tech(s) available"
                elif tool_name == "get_city_production":
                    units = result.get("trainable_units", [])
                    buildings = result.get("constructable_buildings", [])
                    result_summary = f"{len(units)} units, {len(buildings)} buildings"
                # Map visualization tools
                elif tool_name == "get_visible_tiles":
                    tiles = result.get("tiles", [])
                    map_width = result.get("map_width", 0)
                    map_height = result.get("map_height", 0)
                    result_summary = f"{len(tiles)} tiles ({map_width}×{map_height} map)"
                elif tool_name == "get_map_view":
                    center = result.get("center")
                    num_tiles = result.get("num_tiles", 0)
                    num_units = result.get("num_units", 0)
                    center_str = f"({center[0]},{center[1]})" if center else "?"
                    result_summary = f"Map @ {center_str}: {num_tiles} tiles, {num_units} units"
                elif tool_name == "get_unit_build_options":
                    tiles = result.get("tiles", [])
                    total_builds = sum(len(t.get("available_builds", [])) for t in tiles)
                    result_summary = f"{len(tiles)} tiles, {total_builds} build options"
                elif tool_name == "get_reachable_tiles":
                    tiles = result.get("tiles", [])
                    attackable = sum(1 for t in tiles if t.get("can_attack"))
                    result_summary = f"{len(tiles)} tiles ({attackable} attackable)"

            tool_calls.append({
                "name": tool_name,
                "ok": is_ok,
                "category": category,
                "icon": icon,
                "result_summary": result_summary,
                "turn": turn or 0,
                "arguments": arguments,
                "result": result,
            })

        # === GAME EVENTS ===

        if msg_type == "game_start":
            civ = msg.get("civilization", "Unknown")
            leader = msg.get("leader", "Unknown")
            trait = msg.get("trait_description", "")
            game_events.append({
                "event_type": "Game Start",
                "content": f"{leader} of {civ}\n{trait[:100]}...",
                "turn": turn or 0,
            })

        if msg_type == "turn_start":
            game_events.append({
                "event_type": "Turn Start",
                "content": f"Turn {turn} started",
                "turn": turn or 0,
            })

        if msg_type == "turn_complete":
            game_events.append({
                "event_type": "Turn Complete",
                "content": f"Turn {turn} ended",
                "turn": turn or 0,
            })

        # === NOTIFICATIONS ===

        if msg_type == "notification":
            notifications.append({
                "summary": msg.get("summary", ""),
                "message": msg.get("message", ""),
                "turn": msg.get("turn", 0),
                "notif_type": msg.get("notification_type", "?"),
                "x": msg.get("x"),
                "y": msg.get("y"),
            })

    # Track counts before limiting
    debug.conversation_before_limit = len(conversation)
    debug.tools_before_limit = len(tool_calls)
    debug.events_before_limit = len(game_events)
    debug.notifs_before_limit = len(notifications)

    # Only show last N messages to avoid overwhelming the UI
    max_messages = 50
    if len(conversation) > max_messages:
        conversation = conversation[-max_messages:]

    max_tools = 100
    if len(tool_calls) > max_tools:
        tool_calls = tool_calls[-max_tools:]

    max_events = 50
    if len(game_events) > max_events:
        game_events = game_events[-max_events:]

    max_notifs = 50
    if len(notifications) > max_notifs:
        notifications = notifications[-max_notifs:]

    # Track counts after limiting
    debug.conversation_after_limit = len(conversation)
    debug.tools_after_limit = len(tool_calls)
    debug.events_after_limit = len(game_events)
    debug.notifs_after_limit = len(notifications)

    # Reverse so newest is at top
    data["conversation"] = list(reversed(conversation))
    data["tool_calls"] = list(reversed(tool_calls))
    data["game_events"] = list(reversed(game_events))
    data["notifications"] = list(reversed(notifications))

    # Create JSON-safe version of tool_calls for backward compat
    data["tool_calls_json"] = json.dumps(data["tool_calls"])

    # Estimate cost (rough: $0.001 per 1K tokens for cheap models)
    data["estimated_cost"] = data["total_tokens"] * 0.000001

    if debug_mode:
        # Convert defaultdict to regular dict for JSON serialization
        debug.type_counts = dict(debug.type_counts)
        data["debug"] = debug.__dict__

    return data


def parse_observer_logs(game_id: int | None = None) -> dict[str, Any]:
    """Parse observer JSONL logs into per-turn analysis records."""
    data: dict[str, Any] = {
        "observer_turns": [],
        "game_summary": None,
        "has_halt": False,
        "turns_observed": 0,
        "game_id": game_id,
        "available_games": [],
        "last_update": datetime.now().strftime("%H:%M:%S"),
        # Header fields required by the shared template
        "connected": False,
        "current_turn": None,
        "estimated_cost": 0.0,
        "total_tokens": 0,
        "total_requests": 0,
        "debug_mode": False,
        "debug": {},
    }

    if not LOG_DIR.exists():
        return data

    obs_files = list(LOG_DIR.glob("observer_*.jsonl"))
    if not obs_files:
        return data

    game_info = []
    for file_path in obs_files:
        try:
            gid = int(file_path.stem.split("_")[1])
            mtime = file_path.stat().st_mtime
            game_info.append((gid, file_path, mtime))
        except (ValueError, IndexError):
            continue

    if not game_info:
        return data

    game_info.sort(key=lambda x: x[2], reverse=True)

    if game_id is None:
        game_id = game_info[0][0]

    log_file = next((fp for gid, fp, _ in game_info if gid == game_id), None)
    if log_file is None:
        return data

    data["game_id"] = game_id
    data["available_games"] = [
        {"game_id": gid, "is_current": gid == game_id}
        for gid, _, _ in game_info
    ]

    observer_turns = []
    game_summary = None
    has_halt = False

    try:
        with log_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type")
                if mtype == "observer_turn":
                    if msg.get("halted"):
                        has_halt = True
                    observer_turns.append({
                        "turn": msg.get("turn", 0),
                        "outcome": msg.get("outcome", ""),
                        "observation": msg.get("observation", ""),
                        "halted": msg.get("halted", False),
                        "halt_reason": msg.get("halt_reason"),
                        "timestamp": msg.get("timestamp", ""),
                    })
                elif mtype == "observer_game_summary":
                    game_summary = msg.get("analysis", "")
    except FileNotFoundError:
        return data

    data["observer_turns"] = observer_turns
    data["game_summary"] = game_summary
    data["has_halt"] = has_halt
    data["turns_observed"] = len(observer_turns)
    return data


@app.route("/observer")
def observer_view():
    game_id_str = request.args.get("game_id")
    game_id = int(game_id_str) if game_id_str else None
    data = parse_observer_logs(game_id=game_id)
    data["page_data_json"] = json.dumps(data)
    return render_template("dashboard.html", active_tab="observer", **data)


@app.route("/api/observer/data")
def api_observer_data():
    game_id_str = request.args.get("game_id")
    game_id = int(game_id_str) if game_id_str else None
    return parse_observer_logs(game_id=game_id)


@app.route("/api/observer/stream")
def api_observer_stream():
    game_id_str = request.args.get("game_id")
    game_id = int(game_id_str) if game_id_str else None

    def generate():
        data = parse_observer_logs(game_id=game_id)
        yield f"event: update\ndata: {json.dumps(data)}\n\n"
        if _broadcaster:
            q = _broadcaster.subscribe()
            try:
                while True:
                    try:
                        q.get(timeout=30)
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    data = parse_observer_logs(game_id=game_id)
                    yield f"event: update\ndata: {json.dumps(data)}\n\n"
            finally:
                _broadcaster.unsubscribe(q)
        else:
            while True:
                _time.sleep(30)
                yield ": keepalive\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/")
def dashboard():
    debug_mode = request.args.get("debug") == "1"
    game_id_str = request.args.get("game_id")
    game_id = int(game_id_str) if game_id_str else None
    data = parse_logs(debug_mode=debug_mode, game_id=game_id)
    # Build page_data_json for initial JS render (excludes tool_calls_json to avoid redundancy)
    data["page_data_json"] = json.dumps({k: v for k, v in data.items() if k not in ("tool_calls_json",)})
    return render_template("dashboard.html", active_tab="game", **data)


@app.route("/api/data")
def api_data():
    """JSON endpoint for programmatic access."""
    debug_mode = request.args.get("debug") == "1"
    game_id_str = request.args.get("game_id")
    game_id = int(game_id_str) if game_id_str else None
    return parse_logs(debug_mode=debug_mode, game_id=game_id)


@app.route("/api/stream")
def api_stream():
    """SSE stream: push fresh data on each game event.

    Subscribes to the shared EventBroadcaster and pushes immediately on any event.
    Sends keepalives every 30s when idle.
    """
    debug_mode = request.args.get("debug") == "1"
    game_id_str = request.args.get("game_id")
    game_id = int(game_id_str) if game_id_str else None

    def generate():
        # Send initial snapshot immediately so the page populates on connect
        data = parse_logs(debug_mode=debug_mode, game_id=game_id)
        yield f"event: update\ndata: {json.dumps(data)}\n\n"

        if _broadcaster:
            q = _broadcaster.subscribe()
            try:
                while True:
                    try:
                        q.get(timeout=30)
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    # Log is already flushed before broadcaster fires — parse fresh data
                    data = parse_logs(debug_mode=debug_mode, game_id=game_id)
                    yield f"event: update\ndata: {json.dumps(data)}\n\n"
            finally:
                _broadcaster.unsubscribe(q)
        else:
            # No broadcaster (standalone mode) — just send keepalives
            while True:
                _time.sleep(30)
                yield ": keepalive\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main():
    print("Civ V LLM Dashboard")
    print(f"  URL:      http://localhost:5000")
    print(f"  Debug:    http://localhost:5000?debug=1")
    print(f"  Log dir:  {LOG_DIR}")

    if not LOG_DIR.exists():
        logger.warning(f"Log directory does not exist yet: {LOG_DIR}")
    else:
        game_files = list(LOG_DIR.glob("game_*.jsonl"))
        logger.info(f"Found {len(game_files)} game log files in {LOG_DIR}")

    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
