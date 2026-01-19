"""
Civ V LLM Experiment Runner

Simple loop: poll for turns → call LLM → execute tools → repeat until end_turn
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import time
from pathlib import Path
from typing import Any

import requests
import yaml

from agent_runtime.models import get_model
from agent_runtime.tools import build_tools
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


# --- Tool Call Parsing ---

def parse_tool_calls(response: str) -> list[dict[str, Any]]:
    """Extract tool calls from LLM response text.

    Looks for patterns like:
    - mcp_call(tool="get_units", arguments={})
    - mcp_call(tool="send_action", arguments={"action": {"kind": "move_unit", "unit_id": 1001}})
    - end_turn(turn=5)
    """
    tool_calls = []

    def extract_nested_dict(text: str, start_pos: int) -> tuple[str, int] | None:
        """Extract a nested dictionary string, handling braces properly.
        Returns (dict_string, end_position) or None if not found.
        """
        if start_pos >= len(text) or text[start_pos] != '{':
            return None
        
        brace_count = 0
        i = start_pos
        in_string = False
        escape_next = False
        
        while i < len(text):
            char = text[i]
            
            if escape_next:
                escape_next = False
                i += 1
                continue
            
            if char == '\\':
                escape_next = True
                i += 1
                continue
            
            if char == '"' and not escape_next:
                in_string = not in_string
            elif not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        return (text[start_pos:i+1], i + 1)
            
            i += 1
        
        return None

    # Match function_name(args)
    for match in re.finditer(r'(\w+)\(', response):
        func_name = match.group(1)
        args_start = match.end()
        
        # Find matching closing paren, handling nested structures
        paren_count = 1
        i = args_start
        in_string = False
        escape_next = False
        
        while i < len(response) and paren_count > 0:
            char = response[i]
            
            if escape_next:
                escape_next = False
                i += 1
                continue
            
            if char == '\\':
                escape_next = True
            elif char == '"' and not escape_next:
                in_string = not in_string
            elif not in_string:
                if char == '(':
                    paren_count += 1
                elif char == ')':
                    paren_count -= 1
            
            i += 1
        
        if paren_count != 0:
            continue
        
        args_str = response[args_start:i-1]
        
        try:
            # Handle end_turn directly
            if func_name == "end_turn":
                turn_match = re.search(r'turn\s*=\s*(\d+)', args_str)
                if turn_match:
                    tool_calls.append({
                        "tool": "end_turn",
                        "arguments": {"turn": int(turn_match.group(1))}
                    })
                continue

            # Handle mcp_call
            if func_name == "mcp_call":
                # Extract tool name
                tool_match = re.search(r'tool\s*=\s*["\']([^"\']+)["\']', args_str)
                if not tool_match:
                    continue
                
                tool_name = tool_match.group(1)
                
                # Extract arguments dict (handle nested structures)
                args_match = re.search(r'arguments\s*=\s*', args_str)
                if not args_match:
                    continue
                
                dict_start = args_match.end()
                dict_result = extract_nested_dict(args_str, dict_start)
                
                if dict_result:
                    dict_str, _ = dict_result
                    try:
                        # Try JSON first
                        parsed_args = json.loads(dict_str)
                    except json.JSONDecodeError:
                        try:
                            # Fall back to ast.literal_eval for Python dict syntax
                            parsed_args = ast.literal_eval(dict_str)
                        except (ValueError, SyntaxError):
                            parsed_args = {}
                else:
                    parsed_args = {}
                
                # Handle end_turn via mcp_call
                if tool_name == "end_turn":
                    turn = parsed_args.get("turn")
                    if turn is not None:
                        tool_calls.append({
                            "tool": "end_turn",
                            "arguments": {"turn": turn}
                        })
                else:
                    # Regular mcp_call - pass through the tool name and arguments
                    tool_calls.append({
                        "tool": "mcp_call",
                        "arguments": {
                            "tool": tool_name,
                            "arguments": parsed_args
                        }
                    })

        except Exception:
            continue

    return tool_calls


def execute_tool(tool_call: dict[str, Any], tool_registry: dict[str, Any], base_url: str, turn: int) -> dict[str, Any]:
    """Execute a single tool call.
    
    Args:
        tool_call: Dict with 'tool' and 'arguments' keys
        tool_registry: Dict mapping tool names to tool instances
        base_url: Orchestrator base URL
        turn: Current turn number
    """
    name = tool_call.get("tool")
    args = tool_call.get("arguments", {})

    # Handle end_turn specially (direct HTTP call, not via tool registry)
    if name == "end_turn":
        result = call_tool(base_url, "end_turn", {"turn": args.get("turn", turn)})
        result["_end_turn"] = True
        return result

    # Look up tool in registry
    tool = tool_registry.get(name)
    if not tool:
        return {"ok": False, "error": f"Unknown tool: {name}"}

    # Execute the tool
    result = tool.run(args)
    
    # Check if this mcp_call was actually an end_turn
    if name == "mcp_call" and args.get("tool") == "end_turn":
        result["_end_turn"] = True
    
    return result


# --- Core Turn Loop ---

def run_turn(model, tools: list, base_url: str, turn: int, timeout: float | None = None, blockers: list | None = None) -> dict[str, Any]:
    """Run a single turn: LLM → parse → execute → repeat until end_turn.

    Args:
        timeout: Optional timeout in seconds. None means no timeout (wait indefinitely).
    """
    start_time = time.time()

    # Build tool registry (dict mapping tool names to tool instances)
    tool_registry: dict[str, Any] = {}
    for tool in tools:
        tool_name = tool.name() if hasattr(tool, "name") else str(tool)
        tool_registry[tool_name] = tool

    # Build initial messages
    system_prompt = build_system_prompt(tools)
    briefing = generate_turn_briefing(turn, blockers=blockers)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": briefing}
    ]

    iterations = 0
    tool_calls_total = 0

    print(f"  Starting turn {turn}...")

    # Tell logger about current turn so LLM responses get tagged
    if _message_logger:
        _message_logger.set_turn(turn)
        # Log the system prompt and briefing at turn start
        _message_logger.log({
            "type": "turn_start_messages",
            "system_prompt": system_prompt,
            "briefing": briefing,
        }, direction="outgoing")

    while True:
        # Check timeout (if set)
        if timeout is not None and time.time() - start_time >= timeout:
            print(f"  ⚠️  Turn timeout ({timeout}s)")
            break

        iterations += 1

        # Call LLM
        try:
            response = model.generate(messages, temperature=0.2)
            # Remove tool calls from preview (patterns like mcp_call(...) or end_turn(...))
            preview_text = re.sub(r'\w+\([^)]*\)', '', response).strip()
            preview = preview_text[:150] + "..." if len(preview_text) > 150 else preview_text
            print(f"  [{iterations}] LLM: {preview}")
        except Exception as e:
            print(f"  ✗ LLM error: {e}")
            break

        messages.append({"role": "assistant", "content": response})

        # Parse tool calls
        tool_calls = parse_tool_calls(response)

        if not tool_calls:
            # No tool calls - prompt for action
            if iterations >= 3:
                print(f"  ⚠️  No tool calls after {iterations} iterations")
                break
            messages.append({"role": "user", "content": "Please call a tool or end_turn when ready."})
            continue

        # Execute tools
        for call in tool_calls:
            tool_calls_total += 1
            name = call.get("tool", "?")
            inner_tool = call.get("arguments", {}).get("tool", "")
            display = f"{name}({inner_tool})" if inner_tool else name

            try:
                result = execute_tool(call, tool_registry, base_url, turn)
                is_ok = result.get("ok", True)
                print(f"    {'✓' if is_ok else '✗'} {display}")

                # Check for end_turn
                if result.get("_end_turn"):
                    if not is_ok:
                        error = result.get("blocking_type") or result.get("message") or "blocked"
                        print(f"    ⚠️  end_turn blocked: {error}")
                        messages.append({"role": "user", "content": json.dumps(result)})
                    else:
                        # Verify turn actually advanced (turn_end_ack is sent before async completion)
                        print(f"    ⏳ Waiting for turn to advance...")
                        turn_advanced = False
                        for _ in range(20):  # Wait up to 10 seconds
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
                            messages.append({"role": "user", "content": json.dumps({"error": "turn_not_advanced", "message": "end_turn was acknowledged but turn didn't advance. Something may still be blocking."})})
                else:
                    # Add result to conversation
                    messages.append({"role": "user", "content": json.dumps(result)})

            except Exception as e:
                print(f"    ✗ {display}: {e}")
                messages.append({"role": "user", "content": json.dumps({"error": str(e), "tool": name})})

    return {"turn": turn, "iterations": iterations, "tool_calls": tool_calls_total, "success": False}


def archive_logs_for_new_game(game_id: int) -> None:
    """Archive existing log file when starting a new game."""
    if not _message_logger:
        return

    log_file = _message_logger.log_file
    if not log_file.exists() or log_file.stat().st_size == 0:
        return

    # Create archive filename with timestamp
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    archive_name = log_file.stem + f"_game{game_id}_{timestamp}" + log_file.suffix
    archive_path = log_file.parent / "archive" / archive_name

    archive_path.parent.mkdir(parents=True, exist_ok=True)

    # Move current log to archive
    import shutil
    shutil.move(str(log_file), str(archive_path))
    print(f"  📁 Archived previous game log to {archive_path.name}")

    # Create fresh log file
    log_file.touch(exist_ok=True)


def run_game_loop(model, tools: list, base_url: str, poll_interval: float = 2.0, turn_timeout: float | None = None):
    """Main loop: poll for turns, run each turn.

    Args:
        turn_timeout: Optional timeout per turn in seconds. None means no timeout (wait indefinitely).
    """
    print(f"Connecting to {base_url}...")

    # Wait for orchestrator
    for i in range(30):
        if check_health(base_url):
            break
        print(f"  Waiting... ({i+1}/30)")
        time.sleep(1)
    else:
        raise RuntimeError(f"Orchestrator not available at {base_url}")

    print("Connected! Waiting for game...")

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

            # Check for new game (game_id changed)
            if current_game_id is not None and last_game_id is not None and current_game_id != last_game_id:
                print(f"\n{'='*50}")
                print(f"🎮 NEW GAME DETECTED (game_id: {last_game_id} → {current_game_id})")
                print(f"{'='*50}")
                archive_logs_for_new_game(last_game_id)
                last_turn = None  # Reset turn tracking

            # Update tracked game_id
            if current_game_id is not None:
                last_game_id = current_game_id

            # Skip if no new turn
            if current_turn is None or current_turn == last_turn:
                time.sleep(poll_interval)
                continue

            # New turn!
            blockers = status.get("blockers", [])
            print(f"\n{'='*50}")
            print(f"TURN {current_turn} (game_id: {current_game_id})")
            if blockers:
                print(f"Blockers: {[b.get('type') for b in blockers]}")
            print(f"{'='*50}")

            # Update logger with turn info
            if _message_logger:
                _message_logger.set_turn(current_turn, current_game_id)

            result = run_turn(model, tools, base_url, current_turn, turn_timeout, blockers=blockers)

            print(f"  Summary: {result['iterations']} iterations, {result['tool_calls']} tool calls")

            last_turn = current_turn
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nInterrupted")


def main():
    parser = argparse.ArgumentParser(description="Run Civ V LLM experiment")
    parser.add_argument("--config", required=True, help="Config file or short name (e.g., 'gemini')")
    args = parser.parse_args()

    cfg = load_config(args.config)

    # Build model and tools
    base_url = cfg.get("orchestrator", {}).get("url", "http://localhost:8765")
    model = get_model(cfg.get("backend", {}))
    tools = build_tools(cfg.get("tools", []), base_url=base_url)

    print(f"Model: {model.name()}")
    print(f"Tools: {[t.name() if hasattr(t, 'name') else str(t) for t in tools]}")
    print(f"Orchestrator: {base_url}")
    print()

    poll_interval = cfg.get("orchestrator", {}).get("poll_interval", 2.0)
    turn_timeout = cfg.get("orchestrator", {}).get("turn_timeout", None)  # None = no timeout

    run_game_loop(model, tools, base_url, poll_interval, turn_timeout)


if __name__ == "__main__":
    main()
