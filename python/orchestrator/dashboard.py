"""Simple web dashboard for debugging LLM Civ V runs.

Reads from JSONL logs and displays:
- Full LLM conversation (system, user, assistant messages)
- Tool calls with pass/fail status
- Token usage stats

Run: python -m orchestrator.dashboard
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, render_template_string, request

app = Flask(__name__)

LOG_FILE = Path(__file__).parent.parent / "logs" / "messages.jsonl"

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Civ V LLM Dashboard</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'SF Mono', 'Consolas', monospace;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
            line-height: 1.4;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            background: #16213e;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .header h1 { font-size: 18px; color: #0f0; }
        .status { display: flex; gap: 20px; font-size: 14px; }
        .status-item { display: flex; align-items: center; gap: 8px; }
        .dot { width: 10px; height: 10px; border-radius: 50%; }
        .dot.green { background: #0f0; }
        .dot.red { background: #f00; }

        .columns {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            height: calc(100vh - 140px);
        }
        .panel {
            background: #16213e;
            border-radius: 8px;
            padding: 15px;
            overflow-y: auto;
        }
        .panel h2 {
            font-size: 12px;
            text-transform: uppercase;
            color: #888;
            margin-bottom: 12px;
            letter-spacing: 1px;
            position: sticky;
            top: 0;
            background: #16213e;
            padding: 5px 0;
        }

        /* Chat messages */
        .chat-message {
            margin-bottom: 12px;
            padding: 10px 12px;
            border-radius: 8px;
            font-size: 13px;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .chat-message.system {
            background: #2d2d44;
            border-left: 3px solid #888;
            font-size: 11px;
            color: #aaa;
            max-height: 200px;
            overflow-y: auto;
        }
        .chat-message.user {
            background: #1a3a5c;
            border-left: 3px solid #4a9eff;
        }
        .chat-message.assistant {
            background: #1a4a3a;
            border-left: 3px solid #0f0;
        }
        .chat-message .role {
            font-size: 10px;
            text-transform: uppercase;
            color: #888;
            margin-bottom: 4px;
        }
        .chat-message.system .role { color: #888; }
        .chat-message.user .role { color: #4a9eff; }
        .chat-message.assistant .role { color: #0f0; }

        .chat-message .tokens {
            font-size: 10px;
            color: #666;
            margin-top: 6px;
        }

        .turn-divider {
            text-align: center;
            padding: 8px;
            color: #ff0;
            font-size: 12px;
            font-weight: bold;
            border-top: 1px solid #333;
            border-bottom: 1px solid #333;
            margin: 15px 0;
            background: #1a1a2e;
        }

        /* Tool calls */
        .tool-call {
            padding: 8px 10px;
            margin-bottom: 6px;
            border-radius: 4px;
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .tool-call.success {
            background: #1a3a2a;
            border-left: 3px solid #0f0;
        }
        .tool-call.error {
            background: #3a1a1a;
            border-left: 3px solid #f00;
        }
        .tool-call .icon {
            font-size: 14px;
        }
        .tool-call .name {
            flex: 1;
            font-weight: bold;
        }
        .tool-call .turn-badge {
            font-size: 10px;
            background: #333;
            padding: 2px 6px;
            border-radius: 3px;
            color: #888;
        }

        .stats-bar {
            display: flex;
            gap: 20px;
            padding: 10px 15px;
            background: #0d1526;
            border-radius: 6px;
            margin-bottom: 15px;
            font-size: 12px;
        }
        .stat { color: #0ff; }
        .stat-label { color: #666; margin-left: 4px; }

        .empty { color: #666; font-style: italic; padding: 20px; text-align: center; }

        .collapse-btn {
            font-size: 10px;
            color: #666;
            cursor: pointer;
            margin-left: 8px;
        }
        .collapse-btn:hover { color: #aaa; }
    </style>
</head>
<body>
    <div class="header">
        <h1>CIV V LLM DASHBOARD</h1>
        <div class="status">
            <div class="status-item">
                <span class="dot {{ 'green' if connected else 'red' }}"></span>
                {{ 'Connected' if connected else 'Disconnected' }}
            </div>
            <div class="status-item">
                Turn <strong>{{ current_turn or '?' }}</strong>
            </div>
            <div class="status-item" style="color: #888;">
                {{ last_update }}
            </div>
        </div>
    </div>

    <div class="columns">
        <div class="panel">
            <h2>LLM Conversation</h2>
            <div class="stats-bar">
                <span><span class="stat">{{ "{:,}".format(total_tokens) }}</span><span class="stat-label">tokens</span></span>
                <span><span class="stat">{{ total_requests }}</span><span class="stat-label">requests</span></span>
                <span><span class="stat">${{ "%.4f"|format(estimated_cost) }}</span><span class="stat-label">est cost</span></span>
            </div>

            {% if conversation %}
                {% for msg in conversation %}
                    {% if msg.type == 'turn_divider' %}
                    <div class="turn-divider">── Turn {{ msg.turn }} ──</div>
                    {% else %}
                    <div class="chat-message {{ msg.role }}">
                        <div class="role">{{ msg.role }}{% if msg.tokens %} <span class="tokens">({{ msg.tokens }} tok)</span>{% endif %}</div>
                        <div class="content">{{ msg.content }}</div>
                    </div>
                    {% endif %}
                {% endfor %}
            {% else %}
                <div class="empty">No conversation yet</div>
            {% endif %}
        </div>

        <div class="panel">
            <h2>Tool Calls ({{ tool_calls|length }})</h2>
            {% if tool_calls %}
                {% for tool in tool_calls %}
                <div class="tool-call {{ 'success' if tool.ok else 'error' }}">
                    <span class="icon">{{ '✓' if tool.ok else '✗' }}</span>
                    <span class="name">{{ tool.name }}</span>
                    <span class="turn-badge">T{{ tool.turn }}</span>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty">No tool calls yet</div>
            {% endif %}
        </div>
    </div>
    <script>
        // Smart auto-scroll: only scroll to bottom if user was already at bottom
        (function() {
            const chatPanel = document.querySelector('.columns .panel');
            const storageKey = 'dashboard_scroll_state';

            // Check if scrolled to bottom (with small threshold)
            function isAtBottom(el) {
                return el.scrollHeight - el.scrollTop - el.clientHeight < 50;
            }

            // On page load: restore scroll or go to bottom
            function restoreScroll() {
                const saved = sessionStorage.getItem(storageKey);
                if (saved) {
                    const state = JSON.parse(saved);
                    if (state.wasAtBottom) {
                        chatPanel.scrollTop = chatPanel.scrollHeight;
                    } else {
                        chatPanel.scrollTop = state.scrollTop;
                    }
                } else {
                    // First load - scroll to bottom
                    chatPanel.scrollTop = chatPanel.scrollHeight;
                }
            }

            // Before refresh: save scroll state
            function saveScroll() {
                sessionStorage.setItem(storageKey, JSON.stringify({
                    wasAtBottom: isAtBottom(chatPanel),
                    scrollTop: chatPanel.scrollTop
                }));
            }

            // Save state before page unloads (refresh)
            window.addEventListener('beforeunload', saveScroll);

            // Restore on load
            restoreScroll();
        })();
    </script>
</body>
</html>
"""


@dataclass
class ChatMessage:
    role: str  # system, user, assistant
    content: str
    turn: int = 0
    tokens: int = 0
    type: str = "message"  # message or turn_divider


def parse_logs() -> dict[str, Any]:
    """Parse JSONL logs and build conversation + tool call list."""
    data = {
        "connected": False,
        "current_turn": None,
        "total_tokens": 0,
        "total_requests": 0,
        "estimated_cost": 0.0,
        "conversation": [],
        "tool_calls": [],
        "last_update": datetime.now().strftime("%H:%M:%S"),
    }

    if not LOG_FILE.exists():
        return data

    # Parse all messages
    messages = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not messages:
        return data

    # Get connection status and current turn
    for msg in reversed(messages):
        if msg.get("game_id"):
            data["connected"] = True
            break

    for msg in reversed(messages):
        if msg.get("turn") is not None:
            data["current_turn"] = msg["turn"]
            break

    # Build conversation and tool calls
    conversation = []
    tool_calls = []
    seen_turns = set()
    last_turn = None

    # Track request UUIDs to pair with responses
    request_uuids = {}

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

        # Turn start - system prompt and briefing
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

            if uuid:
                request_uuids[uuid] = True

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
            tokens = msg.get("total_tokens", 0) or 0
            prompt_tokens = msg.get("prompt_tokens", 0) or 0
            completion_tokens = msg.get("completion_tokens", 0) or 0

            if response:
                conversation.append({
                    "type": "message",
                    "role": "assistant",
                    "content": response,
                    "turn": turn or 0,
                    "tokens": tokens,
                })

            data["total_tokens"] += tokens

        # Tool calls
        if msg_type == "tool_response":
            tool_name = msg.get("tool", "?")
            result = msg.get("result", {})
            # Check various error indicators
            is_ok = result.get("ok", True)
            if result.get("type") == "error" or result.get("status") == "error":
                is_ok = False

            tool_calls.append({
                "name": tool_name,
                "ok": is_ok,
                "turn": turn or 0,
            })

    # Only show last N messages to avoid overwhelming the UI
    max_messages = 50
    if len(conversation) > max_messages:
        conversation = conversation[-max_messages:]

    # Only show last N tool calls
    max_tools = 100
    if len(tool_calls) > max_tools:
        tool_calls = tool_calls[-max_tools:]

    data["conversation"] = conversation
    data["tool_calls"] = tool_calls

    # Estimate cost (rough: $0.001 per 1K tokens for cheap models)
    data["estimated_cost"] = data["total_tokens"] * 0.000001

    return data


@app.route("/")
def dashboard():
    data = parse_logs()
    return render_template_string(TEMPLATE, **data)


@app.route("/api/data")
def api_data():
    """JSON endpoint for programmatic access."""
    return parse_logs()


def main():
    print("Starting dashboard at http://localhost:5000")
    print("Reading logs from:", LOG_FILE)
    app.run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()
