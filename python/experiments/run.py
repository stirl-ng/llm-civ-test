"""
Civ V LLM Experiment Runner

Simple loop: poll for turns → call LLM → execute tools → repeat until end_turn
"""
from __future__ import annotations

import argparse
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
    - end_turn(turn=5)
    """
    tool_calls = []

    # Match function_name(args)
    for match in re.finditer(r'(\w+)\(([^)]*)\)', response):
        func_name = match.group(1)
        args_str = match.group(2)

        try:
            args = {}

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
                if tool_match:
                    args["tool"] = tool_match.group(1)

                # Extract arguments dict
                args_match = re.search(r'arguments\s*=\s*(\{[^}]*\})', args_str)
                if args_match:
                    try:
                        args["arguments"] = json.loads(args_match.group(1))
                    except json.JSONDecodeError:
                        try:
                            import ast
                            args["arguments"] = ast.literal_eval(args_match.group(1))
                        except (ValueError, SyntaxError):
                            args["arguments"] = {}
                else:
                    args["arguments"] = {}

                # Check if it's end_turn via mcp_call
                if args.get("tool") == "end_turn":
                    turn = args.get("arguments", {}).get("turn")
                    if turn is not None:
                        tool_calls.append({
                            "tool": "end_turn",
                            "arguments": {"turn": turn}
                        })
                        continue

                if "tool" in args:
                    tool_calls.append({"tool": "mcp_call", "arguments": args})

            # Handle update_knowledge_base
            elif func_name == "update_knowledge_base":
                for key in ("operation", "section_id", "content"):
                    match = re.search(rf'{key}\s*=\s*["\']([^"\']+)["\']', args_str)
                    if match:
                        args[key] = match.group(1)
                if args:
                    tool_calls.append({"tool": "update_knowledge_base", "arguments": args})

        except Exception:
            continue

    return tool_calls


def execute_tool(tool_call: dict[str, Any], tools: list, base_url: str, turn: int) -> dict[str, Any]:
    """Execute a single tool call."""
    name = tool_call.get("tool")
    args = tool_call.get("arguments", {})

    # Handle end_turn specially
    if name == "end_turn":
        result = call_tool(base_url, "end_turn", {"turn": args.get("turn", turn)})
        result["_end_turn"] = True
        return result

    # Find and run the tool
    for tool in tools:
        tool_name = tool.name() if hasattr(tool, "name") else str(tool)

        if name == "mcp_call" and tool_name == "mcp_call":
            result = tool.run(args)
            if args.get("tool") == "end_turn":
                result["_end_turn"] = True
            return result

        if name == tool_name:
            return tool.run(args)

    return {"status": "error", "error": f"Unknown tool: {name}"}


# --- Core Turn Loop ---

def run_turn(model, tools: list, base_url: str, turn: int, timeout: float = 300.0) -> dict[str, Any]:
    """Run a single turn: LLM → parse → execute → repeat until end_turn."""
    start_time = time.time()

    # Find MCP tool for briefing
    mcp_tool = next((t for t in tools if getattr(t, "name", lambda: "")() == "mcp_call"), None)

    # Build initial messages
    system_prompt = build_system_prompt(tools, knowledge_base=None)
    briefing = generate_turn_briefing(mcp_tool, None, turn) if mcp_tool else f"Turn {turn}. What would you like to do?"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": briefing}
    ]

    iterations = 0
    tool_calls_total = 0

    print(f"  Starting turn {turn}...")

    while True:
        # Check timeout
        if time.time() - start_time >= timeout:
            print(f"  ⚠️  Turn timeout ({timeout}s)")
            break

        iterations += 1

        # Call LLM
        try:
            response = model.generate(messages, temperature=0.2)
            preview = response[:150] + "..." if len(response) > 150 else response
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
                result = execute_tool(call, tools, base_url, turn)
                status = "✓" if result.get("status") != "error" else "✗"
                print(f"    {status} {display}")

                # Check for end_turn
                if result.get("_end_turn"):
                    if result.get("status") == "error" or "error" in result.get("result", {}):
                        error = result.get("error") or result.get("result", {}).get("message", "blocked")
                        print(f"    ⚠️  end_turn blocked: {error}")
                        messages.append({"role": "user", "content": f"end_turn failed: {error}. Please resolve and try again."})
                    else:
                        print(f"  ✓ Turn {turn} ended")
                        return {"turn": turn, "iterations": iterations, "tool_calls": tool_calls_total, "success": True}
                else:
                    # Add result to conversation
                    messages.append({"role": "user", "content": f"Tool {name} result: {json.dumps(result)}"})

            except Exception as e:
                print(f"    ✗ {display}: {e}")
                messages.append({"role": "user", "content": f"Tool {name} error: {e}"})

    return {"turn": turn, "iterations": iterations, "tool_calls": tool_calls_total, "success": False}


def run_game_loop(model, tools: list, base_url: str, poll_interval: float = 2.0, turn_timeout: float = 300.0):
    """Main loop: poll for turns, run each turn."""
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

    try:
        while True:
            status = get_status(base_url)

            if not status or not status.get("connected"):
                time.sleep(poll_interval)
                continue

            current_turn = status.get("turn")
            if current_turn is None or current_turn == last_turn:
                time.sleep(poll_interval)
                continue

            # New turn!
            print(f"\n{'='*50}")
            print(f"TURN {current_turn}")
            print(f"{'='*50}")

            result = run_turn(model, tools, base_url, current_turn, turn_timeout)

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
    turn_timeout = cfg.get("orchestrator", {}).get("turn_timeout", 300.0)

    run_game_loop(model, tools, base_url, poll_interval, turn_timeout)


if __name__ == "__main__":
    main()
