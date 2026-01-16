from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml
from jsonschema import Draft202012Validator

from agent_runtime import Agent, get_model, build_tools
from agent_runtime.memory import KnowledgeBase
from agent_runtime.strategies.vanilla import VanillaStrategy
from agent_runtime.strategies.enhanced import EnhancedStrategy
from agent_runtime.tools.knowledge_base_tool import KnowledgeBaseTool
from agent_runtime.briefing import generate_turn_briefing
from agent_runtime.prompts.system_prompt import build_system_prompt


def load_schema(python_root: Path, name: str) -> Dict[str, Any]:
    schema_path = python_root / "schemas" / name
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate(obj: Dict[str, Any], schema: Dict[str, Any]) -> None:
    Draft202012Validator(schema).validate(obj)


def load_config(config_arg: str) -> Dict[str, Any]:
    """
    Load config from a path or short name.
    
    If config_arg is a short name (no path separators), looks for it in
    python/configs/experiments/{name}.yaml. Otherwise treats it as a file path.
    """
    config_path = Path(config_arg)
    
    # If it's not an absolute path and has no path separators, treat as short name
    if not config_path.is_absolute() and "/" not in config_arg and "\\" not in config_arg:
        # Resolve relative to python/configs/experiments/
        python_root = Path(__file__).resolve().parent.parent
        config_path = python_root / "configs" / "experiments" / f"{config_arg}.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_strategy(cfg: Dict[str, Any], knowledge_base: KnowledgeBase = None):
    name = (cfg.get("name") or cfg.get("kind") or "enhanced").lower()
    if name == "vanilla":
        return VanillaStrategy(temperature=cfg.get("temperature", 0.2))
    elif name == "enhanced":
        return EnhancedStrategy(
            knowledge_base=knowledge_base,
            temperature=cfg.get("temperature", 0.2)
        )
    raise ValueError(f"Unsupported strategy: {name}")


def dry_run(agent: Agent) -> None:
    # Minimal fake state to exercise the pipeline; real runs come from orchestrator
    state = {"turn": 1}
    actions = agent.step(state)
    print(json.dumps({"agent": agent.name(), "actions": actions}, indent=2))


def call_orchestrator_tool(base_url: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call an orchestrator tool via HTTP."""
    try:
        response = requests.post(
            f"{base_url}/tool",
            json={"tool": tool, "arguments": arguments},
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to call orchestrator tool {tool}: {e}") from e


def check_orchestrator_health(base_url: str) -> bool:
    """Check if orchestrator is running."""
    try:
        response = requests.get(f"{base_url}/health", timeout=5.0)
        response.raise_for_status()
        return response.json().get("status") == "ok"
    except requests.exceptions.RequestException:
        return False


def get_game_status(base_url: str) -> Optional[Dict[str, Any]]:
    """Get current turn status from orchestrator (non-logging endpoint)."""
    try:
        response = requests.get(f"{base_url}/status", timeout=5.0)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None


def send_actions_to_orchestrator(base_url: str, actions: list, notes: str = "") -> Dict[str, Any]:
    """Send actions to orchestrator."""
    if not actions:
        return {"status": "success", "message": "No actions to send"}
    
    # Use send_actions if available, otherwise send individually
    try:
        result = call_orchestrator_tool(base_url, "send_actions", {
            "actions": actions,
            "notes": notes
        })
        return result
    except RuntimeError:
        # Fallback to individual send_action calls
        results = []
        for action in actions:
            try:
                result = call_orchestrator_tool(base_url, "send_action", {
                    "action": action,
                    "notes": notes if len(actions) == 1 else ""
                })
                results.append(result)
            except Exception as e:
                results.append({"status": "error", "error": str(e)})
        return {"status": "success", "results": results}


def end_turn(base_url: str, turn: int) -> Dict[str, Any]:
    """End the current turn."""
    return call_orchestrator_tool(base_url, "end_turn", {"turn": turn})


def _generate_turn_summary(previous_turn: Optional[int], logs_file: Path = Path("logs/llm_messages.jsonl")) -> str:
    """Generate a simple text-based summary of previous turn logs.
    
    Uses the compact log format with turn metadata for filtering.
    
    Args:
        previous_turn: Turn number to summarize (None if no previous turn)
        logs_file: Path to LLM messages JSONL file
        
    Returns:
        Formatted summary string
    """
    if previous_turn is None:
        return ""
    
    if not logs_file.exists():
        return ""
    
    # Read logs from previous turn, filtering by turn field
    turn_logs = []
    try:
        with logs_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    # Filter by turn field (new compact format) or type (old format fallback)
                    entry_turn = entry.get("turn")
                    if entry_turn == previous_turn:
                        # New format: has turn field, include it
                        if entry.get("type") in ("llm_request", "llm_response"):
                            turn_logs.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception:
        # If we can't read logs, return empty summary
        return ""
    
    if not turn_logs:
        return ""
    
    # Simple summary: extract key information from turn logs
    parts = []
    parts.append(f"## Summary of Turn {previous_turn}")
    parts.append("")
    
    # Count tool calls and actions
    tool_calls = 0
    actions_taken = []
    
    for log_entry in turn_logs:
        if log_entry.get("type") == "llm_response":
            response = log_entry.get("response", "")
            # Count tool calls in response
            if "mcp_call" in response or "update_knowledge_base" in response:
                tool_calls += response.count("mcp_call") + response.count("update_knowledge_base")
            
            # Try to extract actions
            if '"kind"' in response:
                # Likely contains action JSON
                try:
                    # Look for JSON action patterns
                    action_matches = re.findall(r'\{"kind"\s*:\s*"[^"]+"[^}]*\}', response)
                    for match in action_matches:
                        try:
                            action = json.loads(match)
                            if "kind" in action:
                                actions_taken.append(action.get("kind", "unknown"))
                        except json.JSONDecodeError:
                            pass
                except Exception:
                    pass
        elif log_entry.get("type") == "llm_request":
            # Extract from latest_message in compact format
            latest_message = log_entry.get("latest_message", {})
            content = latest_message.get("content", "")
            if "mcp_call" in content or "update_knowledge_base" in content:
                tool_calls += content.count("mcp_call") + content.count("update_knowledge_base")
    
    if tool_calls > 0:
        parts.append(f"- Tool calls made: {tool_calls}")
    if actions_taken:
        unique_actions = list(set(actions_taken))
        parts.append(f"- Actions taken: {', '.join(unique_actions[:5])}")
        if len(unique_actions) > 5:
            parts.append(f"  (and {len(unique_actions) - 5} more)")
    
    parts.append("")
    parts.append("(This is a simple summary. Full details are in the logs.)")
    
    return "\n".join(parts)


def _build_turn_prompt(agent: Agent, turn_number: int, summary: str, base_url: str) -> List[Dict[str, str]]:
    """Build initial message list for a turn.
    
    Args:
        agent: Agent instance
        turn_number: Current turn number
        summary: Summary of previous turn(s)
        base_url: Orchestrator base URL
        
    Returns:
        List of message dicts ready for LLM
    """
    # Get tools and knowledge base from agent
    tools = agent.tools
    strategy = agent.strategy
    
    # Get knowledge base from strategy if available
    knowledge_base = None
    if hasattr(strategy, "kb"):
        knowledge_base = strategy.kb
    
    # Find MCP tool for briefing generation
    mcp_tool = None
    for tool in tools:
        tool_name = tool.name() if hasattr(tool, "name") else str(tool)
        if tool_name == "mcp_call":
            mcp_tool = tool
            break
    
    if not mcp_tool:
        # Fallback: create a minimal prompt
        system_prompt = build_system_prompt(tools, knowledge_base)
        messages = [{"role": "system", "content": system_prompt}]
        if summary:
            messages.append({
                "role": "user",
                "content": f"{summary}\n\nIt is now Turn {turn_number}. What would you like to do?"
            })
        else:
            messages.append({
                "role": "user",
                "content": f"It is Turn {turn_number}. What would you like to do?"
            })
        return messages
    
    # Generate turn briefing
    briefing = generate_turn_briefing(mcp_tool, knowledge_base, turn_number)
    
    # Build system prompt
    system_prompt = build_system_prompt(tools, knowledge_base)
    
    # Add summary blurb to system prompt
    if summary:
        system_prompt += "\n\n## Previous Turn Summary\n"
        system_prompt += summary
        system_prompt += "\n\n---\n"
    else:
        # Add note about summaries even if there's no previous summary
        system_prompt += "\n\n## Turn Summaries\n"
        system_prompt += "At the start of each turn, you'll receive a summary of the previous turn's activities. "
        system_prompt += "This helps you maintain context across turns. Use this information to inform your decisions.\n"
        system_prompt += "\n---\n"
    
    # Build messages
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add recent conversation history if available
    if hasattr(strategy, "conversation"):
        recent_messages = strategy.conversation.get_recent_messages(limit=10)
        for msg in recent_messages:
            # Skip messages from current turn
            if msg.get("turn") != turn_number:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
    
    # Add current turn briefing
    messages.append({
        "role": "user",
        "content": briefing
    })
    
    return messages


def _extract_tool_calls_from_response(response: str) -> List[Dict[str, Any]]:
    """Extract tool calls from LLM response text.
    
    Looks for patterns like:
    - mcp_call(tool="get_game_state", arguments={})
    - update_knowledge_base(operation="add", section_id="strategy", content="...")
    - end_turn(turn=5) or mcp_call(tool="end_turn", arguments={"turn": 5})
    
    Args:
        response: Response text from LLM
        
    Returns:
        List of tool call dicts with 'tool' and 'arguments' keys
    """
    tool_calls = []
    
    # Pattern for function calls
    pattern = r'(\w+)\(([^)]+)\)'
    
    for match in re.finditer(pattern, response):
        tool_name = match.group(1)
        args_str = match.group(2)
        
        # Try to parse arguments
        try:
            args = {}
            
            # Special case: end_turn can be called directly or via mcp_call
            if tool_name == "end_turn":
                # Parse turn number
                turn_match = re.search(r'turn\s*=\s*(\d+)', args_str)
                if turn_match:
                    args["turn"] = int(turn_match.group(1))
                    tool_calls.append({
                        "tool": "end_turn",
                        "arguments": args
                    })
                continue
            
            # Look for tool="..." pattern (for mcp_call)
            tool_match = re.search(r'tool\s*=\s*["\']([^"\']+)["\']', args_str)
            if tool_match:
                args["tool"] = tool_match.group(1)
            
            # For mcp_call, if no tool= found, check if first argument is a bare string (tool name)
            if tool_name == "mcp_call" and "tool" not in args:
                # Try to match a bare string argument (e.g., mcp_call(get_game_state))
                # Strip whitespace and try to match a simple identifier
                stripped_args = args_str.strip()
                bare_arg_match = re.search(r'^["\']?([a-zA-Z_][a-zA-Z0-9_]*)["\']?\s*,?\s*$', stripped_args)
                if bare_arg_match:
                    args["tool"] = bare_arg_match.group(1)
                    args["arguments"] = {}  # Default to empty arguments
                else:
                    # Try matching just the first word/identifier if there are multiple args
                    first_word_match = re.search(r'^["\']?([a-zA-Z_][a-zA-Z0-9_]*)', stripped_args)
                    if first_word_match:
                        args["tool"] = first_word_match.group(1)
                        args["arguments"] = {}  # Default to empty arguments
            
            # Look for arguments={...} pattern (handle nested dicts by matching balanced braces)
            # Find the start of arguments=...
            args_start = re.search(r'arguments\s*=\s*\{', args_str)
            if args_start:
                start_pos = args_start.end() - 1  # Position of opening brace
                # Count braces to find matching closing brace
                brace_count = 0
                i = start_pos
                while i < len(args_str):
                    if args_str[i] == '{':
                        brace_count += 1
                    elif args_str[i] == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            # Found matching closing brace
                            args_dict_str = args_str[start_pos:i+1]
                            
                            # Try to parse as JSON first (double quotes)
                            try:
                                parsed_args = json.loads(args_dict_str)
                            except json.JSONDecodeError:
                                # Try converting Python dict syntax to JSON (single quotes -> double quotes)
                                try:
                                    import ast
                                    parsed_args = ast.literal_eval(args_dict_str)
                                except (ValueError, SyntaxError):
                                    # Fallback: try simpler regex for single-level dicts
                                    simple_match = re.search(r'arguments\s*=\s*(\{[^}]+\})', args_str)
                                    if simple_match:
                                        try:
                                            parsed_args = json.loads(simple_match.group(1))
                                        except json.JSONDecodeError:
                                            parsed_args = None
                                    else:
                                        parsed_args = None
                            
                            if parsed_args is not None:
                                if "arguments" in args:
                                    # Merge with existing arguments
                                    args["arguments"].update(parsed_args)
                                else:
                                    args["arguments"] = parsed_args
                            break
                    i += 1
            
            # For knowledge base, parse operation, section_id, content
            if tool_name == "update_knowledge_base":
                op_match = re.search(r'operation\s*=\s*["\']([^"\']+)["\']', args_str)
                if op_match:
                    args["operation"] = op_match.group(1)
                
                sid_match = re.search(r'section_id\s*=\s*["\']([^"\']+)["\']', args_str)
                if sid_match:
                    args["section_id"] = sid_match.group(1)
                
                content_match = re.search(r'content\s*=\s*["\']([^"\']+)["\']', args_str)
                if content_match:
                    args["content"] = content_match.group(1)
            
            # For mcp_call, also check if it's end_turn
            if tool_name == "mcp_call" and args.get("tool") == "end_turn":
                # Extract turn from arguments
                if "arguments" in args and isinstance(args["arguments"], dict):
                    turn = args["arguments"].get("turn")
                    if turn is not None:
                        tool_calls.append({
                            "tool": "end_turn",
                            "arguments": {"turn": turn}
                        })
                        continue
            
            # Add tool call if we have arguments, or if it's mcp_call with a tool name
            if args or (tool_name == "mcp_call" and "tool" in args):
                tool_calls.append({
                    "tool": tool_name,
                    "arguments": args
                })
        except Exception:
            # Skip malformed tool calls
            pass
    
    return tool_calls


def _execute_tool_call(tool_call: Dict[str, Any], tools: List[Any], base_url: str, turn_number: int) -> Dict[str, Any]:
    """Execute a single tool call.
    
    Args:
        tool_call: Tool call dict with 'tool' and 'arguments' keys
        tools: List of available tool instances
        base_url: Orchestrator base URL
        turn_number: Current turn number
        
    Returns:
        Tool result dict. Special marker {"_end_turn": True} if end_turn was called.
    """
    tool_name = tool_call.get("tool")
    tool_args = tool_call.get("arguments", {})
    
    # Special handling for end_turn
    if tool_name == "end_turn":
        turn = tool_args.get("turn", turn_number)
        result = end_turn(base_url, turn)
        # Return special marker
        result["_end_turn"] = True
        return result
    
    # Find the appropriate tool
    for tool in tools:
        tool_instance_name = tool.name() if hasattr(tool, "name") else str(tool)
        
        # TODO handle multiple MCP call types. Lookup how claudecode does it I guess.... or make haiku transform them?
        if tool_name == "mcp_call":
            if tool_instance_name == "mcp_call":
                result = tool.run(tool_args)
                # Check if this mcp_call is actually end_turn
                if tool_args.get("tool") == "end_turn":
                    result["_end_turn"] = True
                return result
        elif tool_name == "update_knowledge_base":
            if tool_instance_name == "update_knowledge_base":
                return tool.run(tool_args)
        elif tool_name == tool_instance_name:
            return tool.run(tool_args)
    
    # Tool not found - provide helpful error message
    available_tools = [tool.name() if hasattr(tool, "name") else str(tool) for tool in tools]
    return {
        "status": "error",
        "error": f"Unknown tool: {tool_name}. Available tools: {', '.join(available_tools) if available_tools else 'none'}"
    }


def _process_turn_loop(
    agent: Agent,
    base_url: str,
    turn_number: int,
    initial_messages: List[Dict[str, str]],
    turn_timeout: float
) -> Dict[str, Any]:
    """Main per-turn conversation loop.
    
    Continues calling LLM, executing tool calls, and adding results to conversation
    until end_turn is called or timeout is reached.
    
    Args:
        agent: Agent instance
        base_url: Orchestrator base URL
        turn_number: Current turn number
        initial_messages: Initial message list for the turn
        turn_timeout: Maximum seconds for the turn
        
    Returns:
        Dict with turn statistics: duration, iterations, tool_calls, actions, errors
    """
    turn_start_time = time.time()
    messages = initial_messages.copy()
    iterations = 0
    tool_call_count = 0
    action_count = 0
    error_count = 0
    end_turn_called = False
    
    # Get model and temperature from agent
    model = agent.model
    strategy = agent.strategy
    tools = agent.tools
    temperature = getattr(strategy, "temperature", 0.2)
    
    print(f"Starting turn loop for turn {turn_number}...")
    
    try:
        while not end_turn_called:
            # Check timeout
            elapsed = time.time() - turn_start_time
            if elapsed >= turn_timeout:
                print(f"⚠️  Turn {turn_number} timeout reached ({elapsed:.2f}s >= {turn_timeout}s)")
                break
            
            iterations += 1
            
            # Call LLM
            print(f"  [Iteration {iterations}] Calling LLM...")
            try:
                response = model.generate(messages, temperature=temperature)
                # Show first 200 chars of response
                response_preview = response[:200] + ("..." if len(response) > 200 else "")
                print(f"  Response: {response_preview}")
            except Exception as e:
                print(f"  Error calling LLM: {e}")
                error_count += 1
                break
            
            # Add assistant response to messages
            messages.append({
                "role": "assistant",
                "content": response
            })
            
            # Extract tool calls from response
            tool_calls = _extract_tool_calls_from_response(response)
            
            if not tool_calls:
                # No tool calls - agent is done (but hasn't called end_turn)
                # We'll wait for explicit end_turn call
                print(f"  No tool calls in response. Waiting for end_turn...")
                # Give it one more iteration to call end_turn
                if iterations >= 2:
                    print(f"  Warning: Agent didn't call end_turn after {iterations} iterations")
                    break
                continue
            
            # Execute tool calls
            print(f"  Executing {len(tool_calls)} tool call(s)...")
            tool_results = []
            
            for tool_call in tool_calls:
                tool_call_count += 1
                tool_name = tool_call.get("tool", "unknown")
                tool_args = tool_call.get("arguments", {})
                
                # Log tool call
                if tool_name == "mcp_call":
                    mcp_tool_name = tool_args.get("tool", "unknown")
                    print(f"    [TOOL] mcp_call({mcp_tool_name})")
                else:
                    print(f"    [TOOL] {tool_name}")
                
                try:
                    result = _execute_tool_call(tool_call, tools, base_url, turn_number)
                    
                    # Log tool result
                    result_status = result.get("status", "unknown")
                    if result_status == "success":
                        print(f"      ✓")
                    elif result_status == "error":
                        error_msg = result.get("error", "Unknown error")
                        # Truncate long error messages
                        if len(error_msg) > 100:
                            error_msg = error_msg[:100] + "..."
                        print(f"      ✗ {error_msg}")
                    else:
                        print(f"      → {result_status}")
                    
                    # Check if end_turn was called
                    if result.get("_end_turn"):
                        print(f"  [END TURN] Called by agent")
                        
                        # Check for errors in end_turn result
                        # Error can be at top level (status="error") or nested in result field
                        is_error = (
                            result.get("status") == "error" or
                            result.get("result", {}).get("type") == "error" or
                            "error" in result or
                            "CANNOT_END_TURN" in str(result)
                        )
                        
                        if is_error:
                            error_count += 1
                            # Try to extract error message from various locations
                            error_msg = (
                                result.get("error") or
                                result.get("result", {}).get("message") or
                                result.get("result", {}).get("error") or
                                "Cannot end turn (blocking condition)"
                            )
                            print(f"  ⚠️  Error ending turn: {error_msg}")
                            print(f"  Turn will continue - agent should resolve blocking condition")
                            # Don't set end_turn_called = True, continue the loop
                        else:
                            end_turn_called = True
                            print(f"  ✓ Turn {turn_number} ended successfully")
                    
                    tool_results.append({
                        "tool": tool_name,
                        "result": result
                    })
                    
                    # Count actions if this was a send_action call
                    if tool_name == "mcp_call":
                        mcp_tool = tool_args.get("tool", "")
                        if mcp_tool == "send_action":
                            action_count += 1
                            print(f"      [ACTION] Action sent")
                    
                except Exception as e:
                    error_count += 1
                    print(f"      ✗ Exception: {e}")
                    tool_results.append({
                        "tool": tool_name,
                        "result": {
                            "status": "error",
                            "error": str(e)
                        }
                    })
            
            # Add tool results to conversation
            if tool_results:
                results_text = "\n".join([
                    f"Tool {r['tool']} result: {json.dumps(r['result'], indent=2)}"
                    for r in tool_results
                ])
                
                messages.append({
                    "role": "user",
                    "content": f"Tool execution results:\n{results_text}\n\nContinue with your response."
                })
            
            if end_turn_called:
                break
    
    except KeyboardInterrupt:
        print(f"\n  Turn loop interrupted by user")
        raise
    except Exception as e:
        print(f"  Error in turn loop: {e}")
        import traceback
        traceback.print_exc()
        error_count += 1
    
    # Calculate final statistics
    turn_duration = time.time() - turn_start_time
    
    return {
        "turn": turn_number,
        "duration": turn_duration,
        "iterations": iterations,
        "tool_calls": tool_call_count,
        "actions": action_count,
        "errors": error_count,
        "end_turn_called": end_turn_called,
        "timed_out": turn_duration >= turn_timeout
    }


def run_game_loop(agent: Agent, base_url: str, poll_interval: float = 2.0, turn_timeout: float = 300.0) -> None:
    """Main game loop that polls for turns and processes them.
    
    Args:
        agent: The agent to run
        base_url: Orchestrator base URL
        poll_interval: Seconds between status polls
        turn_timeout: Maximum seconds per turn (default 5 minutes)
    """
    print(f"Connecting to orchestrator at {base_url}...")
    
    # Wait for orchestrator to be available
    max_wait = 30
    waited = 0
    while not check_orchestrator_health(base_url):
        if waited >= max_wait:
            raise RuntimeError(f"Orchestrator not available at {base_url} after {max_wait} seconds")
        print(f"Waiting for orchestrator... ({waited}/{max_wait}s)")
        time.sleep(1.0)
        waited += 1
    
    print("Orchestrator connected!")
    print(f"Agent: {agent.name()}")
    print(f"Turn timeout: {turn_timeout}s")
    print("Waiting for game to start...")
    
    last_turn: Optional[int] = None
    game_over = False
    
    # Turn and action statistics
    turn_stats: Dict[int, Dict[str, Any]] = {}
    total_actions = 0
    total_action_errors = 0
    
    # Logs file for summary generation
    logs_file = Path("logs/llm_messages.jsonl")
    
    try:
        while not game_over:
            # Check turn status (non-logging endpoint, doesn't spam logs)
            status = get_game_status(base_url)
            
            if status is None or not status.get("connected"):
                # No connection yet, wait and retry
                time.sleep(poll_interval)
                continue
            
            # Extract turn number
            current_turn = status.get("turn")
            
            # Check if this is a new turn
            if current_turn is None:
                # Game not started yet
                time.sleep(poll_interval)
                continue
            
            if last_turn is not None and current_turn == last_turn:
                # Same turn, wait for next turn
                time.sleep(poll_interval)
                continue
            
            # New turn detected!
            print(f"\n{'='*60}")
            print(f"Turn {current_turn} started")
            print(f"{'='*60}")
            
            # Generate summary of previous turn
            if last_turn is not None:
                print(f"Generating summary for turn {last_turn}...")
                summary = _generate_turn_summary(last_turn, logs_file)
                if summary:
                    print("✓ Previous turn summary generated")
                else:
                    print("  (No summary available)")
            else:
                summary = ""
                print("  (First turn - no previous summary)")
            
            # Build initial prompt for this turn
            print("Building turn prompt...")
            initial_messages = _build_turn_prompt(agent, current_turn, summary, base_url)
            print(f"✓ Turn prompt built ({len(initial_messages)} messages)")
            
            # Log turn start
            print(f"[TURN {current_turn} START]")
            
            # Process the turn with continuous tool calling loop
            try:
                turn_result = _process_turn_loop(
                    agent=agent,
                    base_url=base_url,
                    turn_number=current_turn,
                    initial_messages=initial_messages,
                    turn_timeout=turn_timeout
                )
                
                # Extract statistics
                turn_duration = turn_result["duration"]
                turn_iterations = turn_result["iterations"]
                turn_tool_calls = turn_result["tool_calls"]
                turn_actions = turn_result["actions"]
                turn_errors = turn_result["errors"]
                end_turn_called = turn_result["end_turn_called"]
                timed_out = turn_result["timed_out"]
                
                # Update totals
                total_actions += turn_actions
                total_action_errors += turn_errors
                
                # Store turn statistics
                turn_stats[current_turn] = {
                    "turn": current_turn,
                    "duration": turn_duration,
                    "iterations": turn_iterations,
                    "tool_calls": turn_tool_calls,
                    "action_count": turn_actions,
                    "action_errors": turn_errors,
                    "end_turn_called": end_turn_called,
                    "timed_out": timed_out,
                }
                
                # Print turn summary
                print(f"\nTurn {current_turn} summary:")
                print(f"  Duration: {turn_duration:.2f}s")
                print(f"  Iterations: {turn_iterations}")
                print(f"  Tool calls: {turn_tool_calls}")
                print(f"  Actions: {turn_actions} ({turn_errors} errors)")
                if not end_turn_called:
                    print(f"  ⚠️  Turn ended without explicit end_turn call")
                if timed_out:
                    print(f"  ⚠️  TURN TIMEOUT ({turn_duration:.2f}s >= {turn_timeout}s)")
                
                # Check for game over condition
                if not end_turn_called and turn_errors > 0:
                    # Check if error was game over
                    # (This would be in the last tool result, but we don't have it here)
                    # We'll check on next status poll
                    pass
                
                print()
                
                # Log turn end
                print(f"[TURN {current_turn} END]")
                print(f"  Summary: {turn_iterations} iterations, {turn_tool_calls} tool calls, "
                      f"{turn_actions} actions, {turn_errors} errors, {turn_duration:.2f}s")
                
                last_turn = current_turn
                
            except KeyboardInterrupt:
                print("\nInterrupted by user")
                game_over = True
            except Exception as e:
                print(f"Error processing turn: {e}")
                # Record failed turn
                turn_end_time = time.time()
                turn_duration = turn_end_time - time.time()  # Will be corrected below
                turn_stats[current_turn] = {
                    "turn": current_turn,
                    "duration": 0.0,
                    "iterations": 0,
                    "tool_calls": 0,
                    "action_count": 0,
                    "action_errors": 1,
                    "end_turn_called": False,
                    "timed_out": False,
                    "error": str(e),
                }
                # Continue loop, but log the error
                import traceback
                traceback.print_exc()
                time.sleep(poll_interval)
            
            # Small delay before next poll
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\nGame loop interrupted by user")
    except Exception as e:
        print(f"Fatal error in game loop: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    # Print final statistics
    print("\n" + "="*60)
    print("EXPERIMENT STATISTICS")
    print("="*60)
    
    if turn_stats:
        total_turns = len(turn_stats)
        total_duration = sum(s["duration"] for s in turn_stats.values())
        avg_duration = total_duration / total_turns if total_turns > 0 else 0
        max_duration = max(s["duration"] for s in turn_stats.values())
        min_duration = min(s["duration"] for s in turn_stats.values())
        
        timed_out_turns = sum(1 for s in turn_stats.values() if s.get("timed_out", False))
        total_iterations = sum(s.get("iterations", 0) for s in turn_stats.values())
        total_tool_calls = sum(s.get("tool_calls", 0) for s in turn_stats.values())
        
        print(f"Total turns: {total_turns}")
        print(f"Total duration: {total_duration:.2f}s ({total_duration/60:.2f} minutes)")
        print(f"Average turn duration: {avg_duration:.2f}s")
        print(f"Min turn duration: {min_duration:.2f}s")
        print(f"Max turn duration: {max_duration:.2f}s")
        print(f"Turn timeouts: {timed_out_turns}")
        print()
        print(f"Total iterations: {total_iterations}")
        print(f"Total tool calls: {total_tool_calls}")
        print(f"Total actions: {total_actions}")
        print(f"Total action errors: {total_action_errors}")
        if total_actions > 0:
            error_rate = (total_action_errors / total_actions) * 100
            print(f"Action error rate: {error_rate:.2f}%")
        print()
        
        # Show slowest turns
        if total_turns > 0:
            sorted_turns = sorted(turn_stats.items(), key=lambda x: x[1]["duration"], reverse=True)
            print("Slowest 5 turns:")
            for turn_num, stats in sorted_turns[:5]:
                print(f"  Turn {turn_num}: {stats['duration']:.2f}s "
                      f"({stats.get('iterations', 0)} iterations, {stats.get('tool_calls', 0)} tool calls, "
                      f"{stats.get('action_count', 0)} actions, {stats.get('action_errors', 0)} errors)")
    else:
        print("No turns processed")
    
    print("="*60)
    print("Game loop ended")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Civ V LLM experiments")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to experiment YAML config or short name (e.g., 'gemini' for python/configs/experiments/gemini.yaml)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without orchestrator, just one step")
    args = parser.parse_args()

    python_root = Path(__file__).resolve().parent.parent
    cfg = load_config(args.config)

    # Validate experiment config
    exp_schema = load_schema(python_root, "experiment.schema.json")
    validate(cfg, exp_schema)

    # Get orchestrator configuration (needed for tools)
    orchestrator_cfg = cfg.get("orchestrator", {})
    base_url = orchestrator_cfg.get("url", "http://localhost:8765")
    
    # Initialize knowledge base
    knowledge_base = KnowledgeBase()
    
    # Build components
    model = get_model(cfg.get("backend", {}))
    tools = build_tools(cfg.get("tools", []), base_url=base_url)
    
    # Add knowledge base tool
    kb_tool = KnowledgeBaseTool(knowledge_base)
    tools.append(kb_tool)
    
    strategy = build_strategy(cfg.get("strategy", {}), knowledge_base=knowledge_base)
    agent = Agent(model=model, tools=tools, strategy=strategy)

    if args.dry_run:
        dry_run(agent)
        return

    # Get orchestrator configuration (base_url already retrieved above)
    orchestrator_cfg = cfg.get("orchestrator", {})
    pipe_name = orchestrator_cfg.get("pipe", r"\\.\pipe\civv_llm")
    poll_interval = orchestrator_cfg.get("poll_interval", 2.0)
    turn_timeout = orchestrator_cfg.get("turn_timeout", 300.0)
    
    print(f"Orchestrator pipe: {pipe_name}")
    print(f"Orchestrator URL: {base_url}")
    print(f"Poll interval: {poll_interval}s")
    print(f"Turn timeout: {turn_timeout}s")
    print()
    
    # Run the game loop
    run_game_loop(agent, base_url, poll_interval, turn_timeout)


if __name__ == "__main__":
    main()

