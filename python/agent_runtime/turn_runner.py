from __future__ import annotations

import json
import time
from typing import Any

from agent_runtime.context import TurnContext
from agent_runtime.http_client import fetch_turn_state, fetch_notifications
from agent_runtime.models.base import GenerateResponse, ToolCall
from agent_runtime.tools.dispatch import execute_tool
from agent_runtime.tools.schemas import get_openai_tools
from agent_runtime.prompts import build_system_prompt
from agent_runtime.briefing import generate_turn_briefing

try:
    from orchestrator.message_logger import get_message_logger
    _message_logger = get_message_logger()
except ImportError:
    _message_logger = None


# --- Message builders ---

def build_assistant_message(response: GenerateResponse) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": response.text or None}
    if response.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in response.tool_calls
        ]
    if response.raw_model_content is not None:
        msg["_raw"] = response.raw_model_content
    return msg


def build_tool_result_message(tool_call: ToolCall, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "content": json.dumps(result),
    }


# --- Operator input ---

def prompt_operator(turn: int, iteration: int = 0) -> str | None:
    """Prompt the human operator for optional input between iterations."""
    try:
        label = f"  [Turn {turn}]" if iteration == 0 else f"  [Turn {turn}.{iteration}]"
        user_input = input(f"{label} Operator (Enter to continue): ").strip()
        return user_input if user_input else None
    except EOFError:
        return None


# --- Core turn loop ---

def run_turn(
    model,
    ctx: TurnContext,
    timeout: float | None = None,
    interactive: bool = False,
    temperature: float = 0.7,
) -> dict[str, Any]:
    """Run a single turn: LLM → execute tools → repeat until end_turn."""
    start_time = time.time()
    tools = get_openai_tools()

    operator_msg = prompt_operator(ctx.turn) if interactive else None

    system_prompt = build_system_prompt(interactive=interactive)
    state = fetch_turn_state(ctx.base_url)
    briefing = generate_turn_briefing(
        turn_number=ctx.turn,
        game_id=ctx.game_id,
        player_name=ctx.player_name,
        user_message=operator_msg,
        state=state,
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": briefing},
    ]

    iterations = 0
    tool_calls_total = 0
    silent_streak = 0
    halt_reason: str | None = None
    seen_notification_uuids: set[str] = set()

    print(f"  Starting turn {ctx.turn}...")

    if _message_logger:
        _message_logger.set_turn(ctx.turn)
        _message_logger.log({
            "type": "turn_start_messages",
            "system_prompt": system_prompt,
            "briefing": briefing,
        }, direction="outgoing")

    while True:
        if timeout is not None and time.time() - start_time >= timeout:
            print(f"  [!] Turn timeout ({timeout}s)")
            break

        if ctx.halt_check is not None:
            halt_reason = ctx.halt_check()
            if halt_reason:
                print(f"  [!] HALTED by observer: {halt_reason}")
                break

        iterations += 1
        if _message_logger:
            _message_logger.log({"type": "iteration_start", "iteration": iterations}, direction="outgoing")

        # Inject any notifications that arrived since turn start
        new_notifs = [
            n for n in fetch_notifications(ctx.base_url, ctx.turn)
            if n.get("uuid") not in seen_notification_uuids
        ]
        for n in new_notifs:
            seen_notification_uuids.add(n["uuid"])
        if new_notifs:
            lines = [f"- {n['summary']}" for n in new_notifs]
            event_msg = "**[Game Events]**\n" + "\n".join(lines)
            print(f"  [{iterations}] Game events: {[n['summary'] for n in new_notifs]}")
            messages.append({"role": "user", "content": event_msg})

        try:
            response = model.generate(messages, tools=tools, temperature=temperature)
            print(f"  [{iterations}] LLM: {response.text or '(no text)'}")
            if response.tool_calls:
                print(f"  [{iterations}] Tool calls: {[tc.name for tc in response.tool_calls]}")
        except Exception as e:
            print(f"  [x] LLM error: {e}")
            break

        messages.append(build_assistant_message(response))

        if not response.tool_calls:
            silent_streak += 1
            if silent_streak >= 3:
                print(f"  [!] No tool calls after {silent_streak} consecutive silent iterations")
                break
            messages.append({"role": "user", "content": "Please call a tool or end_turn when ready."})
            continue

        silent_streak = 0

        if interactive and iterations > 1:
            mid_turn_msg = prompt_operator(ctx.turn, iterations)
            if mid_turn_msg:
                messages.append({"role": "user", "content": f"**[Operator]:** {mid_turn_msg}"})

        for tool_call in response.tool_calls:
            tool_calls_total += 1

            try:
                result = execute_tool(tool_call, ctx)
                is_ok = result.get("ok", True)
                print(f"    {'[ok]' if is_ok else '[x]'} {tool_call.name}: {json.dumps(result)}")
                if _message_logger:
                    _message_logger.log({
                        "type": "tool_result",
                        "tool": tool_call.name,
                        "arguments": tool_call.arguments,
                        "result": result,
                        "ok": is_ok,
                        "iteration": iterations,
                    }, direction="incoming")
                messages.append(build_tool_result_message(tool_call, result))

                if result.get("_end_turn"):
                    if not is_ok:
                        error = result.get("blocking_type") or result.get("message") or "blocked"
                        print(f"    [!] end_turn blocked: {error}")
                    else:
                        print(f"  [ok] Turn {ctx.turn} ended")
                        return {
                            "turn": ctx.turn,
                            "iterations": iterations,
                            "tool_calls": tool_calls_total,
                            "success": True,
                        }

            except Exception as e:
                print(f"    [x] {tool_call.name}: {e}")
                messages.append(build_tool_result_message(
                    tool_call,
                    {"ok": False, "error": str(e)},
                ))

    result = {"turn": ctx.turn, "iterations": iterations, "tool_calls": tool_calls_total, "success": False}
    if halt_reason:
        result["halted"] = True
        result["reason"] = halt_reason
    return result
