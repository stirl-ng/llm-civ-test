"""Simple web dashboard for debugging LLM Civ V runs.

Reads from JSONL logs and displays:
- Full LLM conversation (system, user, assistant messages)
- Tool calls with pass/fail status
- Token usage stats

Run: python -m orchestrator.dashboard
Add ?debug=1 to URL to see parse diagnostics
Add ?verbose=1 to see game events and internal messages
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, render_template_string, request

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LOG_DIR = Path(__file__).parent.parent / "logs"

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Civ V LLM Dashboard</title>
    <style>
        :root {
            --bg-dark: #0f0f1a;
            --bg-panel: #1a1a2e;
            --bg-panel-alt: #16213e;
            --bg-input: #0d1526;
            --accent-green: #00ff88;
            --accent-blue: #4a9eff;
            --accent-cyan: #00d4ff;
            --accent-yellow: #ffd93d;
            --accent-red: #ff6b6b;
            --accent-purple: #a855f7;
            --accent-orange: #ff9f43;
            --text-primary: #e8e8e8;
            --text-secondary: #888;
            --text-muted: #555;
            --border-subtle: #2a2a4a;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        html, body {
            height: 100%;
            overflow: hidden;
        }

        body {
            font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;
            background: var(--bg-dark);
            color: var(--text-primary);
            padding: 16px;
            line-height: 1.5;
            display: flex;
            flex-direction: column;
        }

        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: var(--bg-dark);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb {
            background: var(--border-subtle);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-muted);
        }

        /* Header */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 20px;
            background: linear-gradient(135deg, var(--bg-panel) 0%, var(--bg-panel-alt) 100%);
            border-radius: 12px;
            margin-bottom: 16px;
            flex-shrink: 0;
            border: 1px solid var(--border-subtle);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }

        .header h1 {
            font-size: 16px;
            font-weight: 600;
            letter-spacing: 2px;
            background: linear-gradient(90deg, var(--accent-green), var(--accent-cyan));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .status {
            display: flex;
            gap: 24px;
            font-size: 13px;
            align-items: center;
        }

        .status-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            animation: pulse 2s ease-in-out infinite;
        }
        .dot.green {
            background: var(--accent-green);
            box-shadow: 0 0 10px var(--accent-green);
        }
        .dot.red {
            background: var(--accent-red);
            box-shadow: 0 0 10px var(--accent-red);
            animation: none;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .turn-display {
            font-size: 20px;
            font-weight: 700;
            color: var(--accent-yellow);
        }

        .game-selector {
            position: relative;
            display: inline-block;
        }

        .game-selector-btn {
            background: var(--bg-input);
            border: 1px solid var(--border-subtle);
            color: var(--text-primary);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s ease;
            font-family: inherit;
        }

        .game-selector-btn:hover {
            background: var(--bg-panel-alt);
            border-color: var(--accent-cyan);
        }

        .game-selector-dropdown {
            display: none;
            position: absolute;
            top: 100%;
            right: 0;
            margin-top: 4px;
            background: var(--bg-panel);
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            min-width: 200px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
            z-index: 1000;
        }

        .game-selector:hover .game-selector-dropdown {
            display: block;
        }

        .game-selector-item {
            padding: 10px 12px;
            color: var(--text-secondary);
            text-decoration: none;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            transition: background 0.2s ease;
            border-bottom: 1px solid var(--border-subtle);
        }

        .game-selector-item:last-child {
            border-bottom: none;
        }

        .game-selector-item:hover {
            background: var(--bg-input);
            color: var(--text-primary);
        }

        .game-selector-item.current {
            background: var(--bg-input);
            color: var(--accent-cyan);
            font-weight: 600;
        }

        .game-selector-item .game-id {
            font-weight: 600;
        }

        .game-selector-item .msg-count {
            color: var(--text-muted);
            font-size: 10px;
        }

        /* Main layout */
        .columns {
            display: grid;
            grid-template-columns: 5fr 3fr;
            gap: 16px;
            flex: 1;
            min-height: 0;
        }

        .right-column {
            display: flex;
            flex-direction: column;
            gap: 16px;
            min-height: 0;
        }

        /* Panels */
        .panel {
            background: var(--bg-panel);
            border-radius: 12px;
            padding: 16px;
            overflow-y: auto;
            min-height: 0;
            border: 1px solid var(--border-subtle);
        }

        .panel.half {
            flex: 1 1 0;
            overflow-y: auto;
        }

        .panel h2 {
            font-size: 11px;
            text-transform: uppercase;
            color: var(--text-secondary);
            margin-bottom: 12px;
            letter-spacing: 1.5px;
            position: sticky;
            top: 0;
            background: var(--bg-panel);
            padding: 4px 0 8px 0;
            z-index: 10;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .panel h2::before {
            content: '';
            display: inline-block;
            width: 3px;
            height: 12px;
            background: var(--accent-cyan);
            border-radius: 2px;
        }

        .count-badge {
            font-size: 10px;
            background: var(--bg-input);
            padding: 2px 8px;
            border-radius: 10px;
            color: var(--text-muted);
            font-weight: normal;
        }

        /* Stats bar */
        .stats-bar {
            display: flex;
            gap: 24px;
            padding: 12px 16px;
            background: var(--bg-input);
            border-radius: 8px;
            margin-bottom: 16px;
            font-size: 12px;
            border: 1px solid var(--border-subtle);
        }

        .stat {
            color: var(--accent-cyan);
            font-weight: 600;
            font-size: 14px;
        }

        .stat-label {
            color: var(--text-muted);
            margin-left: 6px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* Chat messages */
        .chat-message {
            margin-bottom: 12px;
            padding: 12px 14px;
            border-radius: 8px;
            font-size: 12px;
            white-space: pre-wrap;
            word-wrap: break-word;
            border-left: 3px solid transparent;
            transition: transform 0.1s ease, box-shadow 0.1s ease;
        }

        .chat-message:hover {
            transform: translateX(2px);
        }

        .chat-message.system {
            background: linear-gradient(135deg, #252540 0%, #1a1a30 100%);
            border-left-color: var(--text-muted);
            font-size: 11px;
            color: var(--text-secondary);
            max-height: 150px;
            overflow-y: auto;
        }

        .chat-message.user {
            background: linear-gradient(135deg, #1a3a5c 0%, #152a45 100%);
            border-left-color: var(--accent-blue);
        }

        .chat-message.assistant {
            background: linear-gradient(135deg, #1a4a3a 0%, #153a2d 100%);
            border-left-color: var(--accent-green);
        }

        .chat-message .role {
            font-size: 9px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 6px;
            font-weight: 600;
        }

        .chat-message.system .role { color: var(--text-muted); }
        .chat-message.user .role { color: var(--accent-blue); }
        .chat-message.assistant .role { color: var(--accent-green); }

        .chat-message .tokens {
            font-size: 10px;
            color: var(--text-muted);
            font-weight: normal;
            margin-left: 8px;
        }

        .chat-message .content {
            line-height: 1.6;
        }

        /* Turn divider */
        .turn-divider {
            text-align: center;
            padding: 10px 16px;
            color: var(--accent-yellow);
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 2px;
            margin: 16px 0;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
        }

        .turn-divider::before,
        .turn-divider::after {
            content: '';
            flex: 1;
            height: 1px;
            background: linear-gradient(90deg, transparent, var(--accent-yellow), transparent);
        }

        /* Tool calls */
        .tool-call {
            padding: 10px 12px;
            margin-bottom: 8px;
            border-radius: 6px;
            font-size: 11px;
            transition: transform 0.1s ease;
        }

        .tool-call:hover {
            transform: translateX(2px);
        }

        .tool-call.query {
            background: linear-gradient(135deg, #1a2a4a 0%, #152238 100%);
            border-left: 3px solid var(--accent-blue);
        }

        .tool-call.action {
            background: linear-gradient(135deg, #3a2a1a 0%, #2d2215 100%);
            border-left: 3px solid var(--accent-orange);
        }

        .tool-call.error {
            background: linear-gradient(135deg, #3a1a1a 0%, #2d1515 100%);
            border-left: 3px solid var(--accent-red);
        }

        .tool-call-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 6px;
        }

        .tool-call .icon {
            font-size: 12px;
            width: 18px;
            height: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            flex-shrink: 0;
        }

        .tool-call.query .icon {
            background: rgba(74, 158, 255, 0.2);
            color: var(--accent-blue);
        }

        .tool-call.action .icon {
            background: rgba(255, 159, 67, 0.2);
            color: var(--accent-orange);
        }

        .tool-call.error .icon {
            background: rgba(255, 107, 107, 0.2);
            color: var(--accent-red);
        }

        .tool-call .name {
            flex: 1;
            font-weight: 600;
            font-family: inherit;
        }

        .tool-call .turn-badge {
            font-size: 9px;
            background: var(--bg-input);
            padding: 3px 8px;
            border-radius: 4px;
            color: var(--text-muted);
        }

        .tool-call-result {
            font-size: 10px;
            color: var(--text-secondary);
            padding-left: 28px;
            line-height: 1.4;
        }

        .tool-call-result.success {
            color: var(--accent-green);
        }

        .tool-call-result.error {
            color: var(--accent-red);
        }

        /* Notifications */
        .notification {
            padding: 10px 12px;
            margin-bottom: 8px;
            border-radius: 6px;
            font-size: 11px;
            background: linear-gradient(135deg, #1a2a4a 0%, #152238 100%);
            border-left: 3px solid var(--accent-blue);
            transition: transform 0.1s ease;
        }

        .notification:hover {
            transform: translateX(2px);
        }

        .notification .summary {
            font-weight: 600;
            color: var(--accent-blue);
            margin-bottom: 4px;
        }

        .notification .message {
            color: var(--text-secondary);
            font-size: 10px;
            line-height: 1.4;
        }

        .notification .meta {
            font-size: 9px;
            color: var(--text-muted);
            margin-top: 6px;
            display: flex;
            gap: 12px;
        }

        /* Game event */
        .game-event {
            padding: 10px 12px;
            margin-bottom: 8px;
            border-radius: 6px;
            font-size: 11px;
            background: linear-gradient(135deg, #2a1a4a 0%, #1f1538 100%);
            border-left: 3px solid var(--accent-purple);
        }

        .game-event .event-type {
            font-weight: 600;
            color: var(--accent-purple);
            margin-bottom: 4px;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .game-event .event-content {
            color: var(--text-secondary);
            font-size: 10px;
            line-height: 1.4;
        }

        .empty {
            color: var(--text-muted);
            font-style: italic;
            padding: 30px;
            text-align: center;
            font-size: 12px;
        }

        /* Debug panel */
        .debug-panel {
            background: linear-gradient(135deg, #2a1a3a 0%, #1a1528 100%);
            border: 1px solid var(--accent-purple);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            font-size: 11px;
        }

        .debug-panel h3 {
            color: var(--accent-purple);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .debug-panel h3::before {
            content: '🔍';
        }

        .debug-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }

        .debug-section {
            background: rgba(0, 0, 0, 0.2);
            padding: 12px;
            border-radius: 6px;
        }

        .debug-section h4 {
            color: var(--text-secondary);
            font-size: 10px;
            text-transform: uppercase;
            margin-bottom: 8px;
            letter-spacing: 0.5px;
        }

        .debug-item {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        .debug-item:last-child {
            border-bottom: none;
        }

        .debug-key {
            color: var(--text-muted);
        }

        .debug-value {
            color: var(--accent-cyan);
            font-weight: 500;
        }

        .debug-value.warning {
            color: var(--accent-yellow);
        }

        .debug-value.error {
            color: var(--accent-red);
        }

        .toggle-buttons {
            position: fixed;
            bottom: 16px;
            right: 16px;
            display: flex;
            gap: 8px;
            z-index: 100;
        }

        .toggle-btn {
            background: var(--bg-panel);
            border: 1px solid var(--border-subtle);
            color: var(--text-secondary);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 11px;
            text-decoration: none;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .toggle-btn:hover {
            background: var(--bg-panel-alt);
            transform: translateY(-1px);
        }

        .toggle-btn.active {
            background: var(--bg-panel-alt);
            border-color: var(--accent-purple);
            color: var(--accent-purple);
        }

        .toggle-btn.active:hover {
            border-color: var(--accent-cyan);
            color: var(--accent-cyan);
        }

        /* Unrecognized types list */
        .unrecognized-list {
            font-family: inherit;
            font-size: 10px;
        }

        .unrecognized-item {
            color: var(--accent-yellow);
            padding: 2px 0;
        }

        /* Modal */
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .modal-overlay.visible {
            display: flex;
        }

        .modal-content {
            background: var(--bg-panel);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            max-width: 900px;
            max-height: 90vh;
            width: 100%;
            display: flex;
            flex-direction: column;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
        }

        .modal-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-subtle);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .modal-header h3 {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .modal-close {
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 20px;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 4px;
            transition: all 0.2s ease;
        }

        .modal-close:hover {
            background: var(--bg-input);
            color: var(--text-primary);
        }

        .modal-body {
            padding: 20px;
            overflow-y: auto;
            flex: 1;
        }

        .modal-section {
            margin-bottom: 20px;
        }

        .modal-section:last-child {
            margin-bottom: 0;
        }

        .modal-section h4 {
            font-size: 11px;
            text-transform: uppercase;
            color: var(--accent-cyan);
            margin-bottom: 10px;
            letter-spacing: 1px;
        }

        .modal-json {
            background: var(--bg-input);
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            padding: 12px;
            font-family: 'JetBrains Mono', 'SF Mono', monospace;
            font-size: 11px;
            line-height: 1.6;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
            color: var(--text-secondary);
        }

        .tool-call {
            cursor: pointer;
            position: relative;
        }

        .tool-call::after {
            content: '›';
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            font-size: 16px;
            opacity: 0;
            transition: opacity 0.2s ease;
        }

        .tool-call:hover {
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
        }

        .tool-call:hover::after {
            opacity: 1;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>◈ CIV V LLM DASHBOARD</h1>
        <div class="status">
            <div class="status-item">
                <span class="dot {{ 'green' if connected else 'red' }}"></span>
                {{ 'Connected' if connected else 'Disconnected' }}
            </div>
            <div class="status-item">
                Turn <span class="turn-display">{{ current_turn or '—' }}</span>
            </div>
            {% if available_games %}
            <div class="status-item">
                <div class="game-selector">
                    <button class="game-selector-btn">
                        Game {{ game_id or '—' }}
                        <span>▾</span>
                    </button>
                    <div class="game-selector-dropdown">
                        {% for game in available_games %}
                        <a href="?game_id={{ game.game_id }}{% if debug_mode %}&debug=1{% endif %}{% if verbose_mode %}&verbose=1{% endif %}"
                           class="game-selector-item {{ 'current' if game.is_current else '' }}">
                            <span class="game-id">{{ game.game_id }}</span>
                            <span class="msg-count">{{ game.message_count }} msgs</span>
                        </a>
                        {% endfor %}
                    </div>
                </div>
            </div>
            {% endif %}
            <div class="status-item" style="color: var(--text-muted);">
                {{ last_update }}
            </div>
        </div>
    </div>

    {% if debug_mode %}
    <div class="debug-panel">
        <h3>Parse Diagnostics</h3>
        <div class="debug-grid">
            <div class="debug-section">
                <h4>File Stats</h4>
                <div class="debug-item">
                    <span class="debug-key">Log file</span>
                    <span class="debug-value">{{ debug.log_file_name }}</span>
                </div>
                <div class="debug-item">
                    <span class="debug-key">File exists</span>
                    <span class="debug-value {% if not debug.file_exists %}error{% endif %}">{{ 'Yes' if debug.file_exists else 'No' }}</span>
                </div>
                <div class="debug-item">
                    <span class="debug-key">Total lines</span>
                    <span class="debug-value">{{ debug.total_lines }}</span>
                </div>
                <div class="debug-item">
                    <span class="debug-key">Parse errors</span>
                    <span class="debug-value {% if debug.parse_errors > 0 %}error{% endif %}">{{ debug.parse_errors }}</span>
                </div>
                <div class="debug-item">
                    <span class="debug-key">Empty lines</span>
                    <span class="debug-value">{{ debug.empty_lines }}</span>
                </div>
            </div>

            <div class="debug-section">
                <h4>Message Types Found</h4>
                {% for msg_type, count in debug.type_counts.items() %}
                <div class="debug-item">
                    <span class="debug-key">{{ msg_type or '(no type)' }}</span>
                    <span class="debug-value">{{ count }}</span>
                </div>
                {% endfor %}
            </div>

            <div class="debug-section">
                <h4>Display Limits</h4>
                <div class="debug-item">
                    <span class="debug-key">Conversation (max 50)</span>
                    <span class="debug-value {% if debug.conversation_before_limit > 50 %}warning{% endif %}">{{ debug.conversation_before_limit }} → {{ debug.conversation_after_limit }}</span>
                </div>
                <div class="debug-item">
                    <span class="debug-key">Tool calls (max 100)</span>
                    <span class="debug-value {% if debug.tools_before_limit > 100 %}warning{% endif %}">{{ debug.tools_before_limit }} → {{ debug.tools_after_limit }}</span>
                </div>
                <div class="debug-item">
                    <span class="debug-key">Game events (max 50)</span>
                    <span class="debug-value {% if debug.events_before_limit > 50 %}warning{% endif %}">{{ debug.events_before_limit }} → {{ debug.events_after_limit }}</span>
                </div>
                <div class="debug-item">
                    <span class="debug-key">Notifications (max 50)</span>
                    <span class="debug-value {% if debug.notifs_before_limit > 50 %}warning{% endif %}">{{ debug.notifs_before_limit }} → {{ debug.notifs_after_limit }}</span>
                </div>
            </div>

            {% if debug.unrecognized_types %}
            <div class="debug-section">
                <h4>Unrecognized Message Types</h4>
                <div class="unrecognized-list">
                    {% for t in debug.unrecognized_types %}
                    <div class="unrecognized-item">{{ t }}</div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}
        </div>
    </div>
    {% endif %}

    <div class="columns">
        <div class="panel">
            <h2>LLM Conversation <span class="count-badge">{{ conversation|length }}</span></h2>
            <div class="stats-bar">
                <span><span class="stat">{{ "{:,}".format(total_tokens) }}</span><span class="stat-label">tokens</span></span>
                <span><span class="stat">{{ total_requests }}</span><span class="stat-label">requests</span></span>
                <span><span class="stat">${{ "%.4f"|format(estimated_cost) }}</span><span class="stat-label">est cost</span></span>
            </div>

            <div class="conversation-messages">
            {% if conversation %}
                {% for msg in conversation %}
                    {% if msg.type == 'turn_divider' %}
                    <div class="turn-divider">TURN {{ msg.turn }}</div>
                    {% else %}
                    <div class="chat-message {{ msg.role }}">
                        <div class="role">{{ msg.role }}{% if msg.tokens %}<span class="tokens">{{ msg.tokens }} tok</span>{% endif %}</div>
                        <div class="content">{{ msg.content }}</div>
                    </div>
                    {% endif %}
                {% endfor %}
            {% else %}
                <div class="empty">No conversation yet — waiting for LLM activity</div>
            {% endif %}
            </div>
        </div>

        <div class="right-column">
            <div class="panel half">
                <h2>Tool Activity <span class="count-badge">{{ tool_calls|length }}</span></h2>
                <div class="tool-calls-container">
                {% if tool_calls %}
                    {% for tool in tool_calls %}
                    <div class="tool-call {{ tool.category }} {{ 'error' if not tool.ok else '' }}" onclick="openToolModal({{ loop.index0 }})">
                        <div class="tool-call-header">
                            <span class="icon">{{ tool.icon }}</span>
                            <span class="name">{{ tool.name }}</span>
                            <span class="turn-badge">T{{ tool.turn }}</span>
                        </div>
                        {% if tool.result_summary %}
                        <div class="tool-call-result {{ 'success' if tool.ok else 'error' }}">{{ tool.result_summary }}</div>
                        {% endif %}
                    </div>
                    {% endfor %}
                {% else %}
                    <div class="empty">No tool calls yet</div>
                {% endif %}
                </div>
            </div>

            {% if verbose_mode %}
            <div class="panel half">
                <h2>Game Events <span class="count-badge">{{ game_events|length }}</span></h2>
                <div class="events-container">
                {% if game_events %}
                    {% for event in game_events %}
                    <div class="game-event">
                        <div class="event-type">{{ event.event_type }}</div>
                        <div class="event-content">{{ event.content }}</div>
                    </div>
                    {% endfor %}
                {% else %}
                    <div class="empty">No game events yet</div>
                {% endif %}
                </div>
            </div>
            {% else %}
            <div class="panel half">
                <h2>Notifications <span class="count-badge">{{ notifications|length }}</span></h2>
                <div class="notifications-container">
                {% if notifications %}
                    {% for notif in notifications %}
                    <div class="notification">
                        <div class="summary">{{ notif.summary }}</div>
                        {% if notif.message and notif.message != notif.summary %}
                        <div class="message">{{ notif.message }}</div>
                        {% endif %}
                        <div class="meta">
                            <span>T{{ notif.turn }}</span>
                            <span>Type {{ notif.notif_type }}</span>
                        </div>
                    </div>
                    {% endfor %}
                {% else %}
                    <div class="empty">No notifications yet</div>
                {% endif %}
                </div>
            </div>
            {% endif %}
        </div>
    </div>

    <div class="toggle-buttons">
        <a href="?{% if game_id %}game_id={{ game_id }}&{% endif %}{% if not debug_mode %}debug=1{% endif %}{% if verbose_mode %}&verbose=1{% endif %}"
           class="toggle-btn {% if debug_mode %}active{% endif %}">
            🔍 Debug
        </a>
        <a href="?{% if game_id %}game_id={{ game_id }}&{% endif %}{% if debug_mode %}debug=1&{% endif %}{% if not verbose_mode %}verbose=1{% endif %}"
           class="toggle-btn {% if verbose_mode %}active{% endif %}">
            📋 Verbose
        </a>
    </div>

    <!-- Tool Detail Modal -->
    <div class="modal-overlay" id="toolModal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>
                    <span id="modalIcon"></span>
                    <span id="modalToolName"></span>
                </h3>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="modal-section">
                    <h4>Arguments</h4>
                    <pre class="modal-json" id="modalArguments"></pre>
                </div>
                <div class="modal-section">
                    <h4>Response</h4>
                    <pre class="modal-json" id="modalResult"></pre>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Tool data for modal
        const toolData = {{ tool_calls_json|safe }};

        function openToolModal(index) {
            const tool = toolData[index];
            if (!tool) return;

            document.getElementById('modalIcon').textContent = tool.icon;
            document.getElementById('modalToolName').textContent = tool.name;

            // Handle empty or null arguments/results
            const args = tool.arguments || {};
            const result = tool.result || {};

            document.getElementById('modalArguments').textContent = JSON.stringify(args, null, 2);

            // Special handling for map results - display the ASCII map directly
            if (result.map && typeof result.map === 'string') {
                // Show map as pre-formatted text, then other fields as JSON
                const { map, ...otherFields } = result;
                let displayText = '=== ASCII Map ===\n\n' + map + '\n\n';
                if (Object.keys(otherFields).length > 0) {
                    displayText += '=== Other Data ===\n\n' + JSON.stringify(otherFields, null, 2);
                }
                document.getElementById('modalResult').textContent = displayText;
            } else {
                document.getElementById('modalResult').textContent = JSON.stringify(result, null, 2);
            }

            document.getElementById('toolModal').classList.add('visible');
        }

        function closeModal() {
            document.getElementById('toolModal').classList.remove('visible');
        }

        // Close modal on escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeModal();
            }
        });

        // Close modal on overlay click
        document.getElementById('toolModal').addEventListener('click', function(e) {
            if (e.target === this) {
                closeModal();
            }
        });

        // Auto-refresh without closing modals
        let refreshInterval;

        function isModalOpen() {
            return document.getElementById('toolModal').classList.contains('visible');
        }

        async function refreshData() {
            // Don't refresh if modal is open
            if (isModalOpen()) {
                return;
            }

            try {
                const params = new URLSearchParams(window.location.search);
                const response = await fetch('/api/data?' + params.toString());
                if (!response.ok) return;

                const data = await response.json();

                // Update header status
                updateHeader(data);

                // Update stats
                updateStats(data);

                // Update conversation
                updateConversation(data);

                // Update tool calls
                updateToolCalls(data);

                // Update notifications or events (depending on verbose mode)
                updateRightPanel(data);

                // Update debug panel if in debug mode
                if (data.debug_mode && data.debug) {
                    updateDebugPanel(data);
                }
            } catch (error) {
                console.error('Refresh failed:', error);
            }
        }

        function updateHeader(data) {
            // Update connection status
            const dot = document.querySelector('.dot');
            const statusText = dot.parentElement.childNodes[2];
            if (data.connected) {
                dot.className = 'dot green';
                statusText.textContent = 'Connected';
            } else {
                dot.className = 'dot red';
                statusText.textContent = 'Disconnected';
            }

            // Update turn display
            const turnDisplay = document.querySelector('.turn-display');
            if (turnDisplay) {
                turnDisplay.textContent = data.current_turn || '—';
            }

            // Update last update time
            const timeElements = document.querySelectorAll('.status-item');
            const lastElement = timeElements[timeElements.length - 1];
            if (lastElement) {
                lastElement.textContent = data.last_update;
            }
        }

        function updateStats(data) {
            const statsBar = document.querySelector('.stats-bar');
            if (statsBar) {
                const tokens = data.total_tokens.toLocaleString();
                const requests = data.total_requests;
                const cost = data.estimated_cost.toFixed(4);
                statsBar.innerHTML = `
                    <span><span class="stat">${tokens}</span><span class="stat-label">tokens</span></span>
                    <span><span class="stat">${requests}</span><span class="stat-label">requests</span></span>
                    <span><span class="stat">$${cost}</span><span class="stat-label">est cost</span></span>
                `;
            }
        }

        function updateConversation(data) {
            const conversationPanel = document.querySelector('.panel');
            if (!conversationPanel) return;

            const countBadge = conversationPanel.querySelector('.count-badge');
            if (countBadge) {
                countBadge.textContent = data.conversation.length;
            }

            // Save scroll position
            const scrollPos = conversationPanel.scrollTop;
            const wasAtBottom = scrollPos + conversationPanel.clientHeight >= conversationPanel.scrollHeight - 50;

            // Find the conversation container
            const conversationContainer = conversationPanel.querySelector('.conversation-messages');
            if (!conversationContainer) return;

            if (data.conversation.length === 0) {
                conversationContainer.innerHTML = '<div class="empty">No conversation yet — waiting for LLM activity</div>';
            } else {
                let html = '';
                for (const msg of data.conversation) {
                    if (msg.type === 'turn_divider') {
                        html += `<div class="turn-divider">TURN ${msg.turn}</div>`;
                    } else {
                        const tokens = msg.tokens ? `<span class="tokens">${msg.tokens} tok</span>` : '';
                        html += `
                            <div class="chat-message ${msg.role}">
                                <div class="role">${msg.role}${tokens}</div>
                                <div class="content">${escapeHtml(msg.content)}</div>
                            </div>
                        `;
                    }
                }
                conversationContainer.innerHTML = html;
            }

            // Restore scroll (or scroll to bottom if was at bottom)
            if (wasAtBottom) {
                conversationPanel.scrollTop = conversationPanel.scrollHeight;
            } else {
                conversationPanel.scrollTop = scrollPos;
            }
        }

        function updateToolCalls(data) {
            const toolPanel = document.querySelector('.panel.half');
            if (!toolPanel) return;

            const countBadge = toolPanel.querySelector('.count-badge');
            if (countBadge) {
                countBadge.textContent = data.tool_calls.length;
            }

            // Update global toolData for modal
            toolData.length = 0;
            toolData.push(...data.tool_calls);

            // Save scroll position
            const scrollPos = toolPanel.scrollTop;

            // Find container
            const container = toolPanel.querySelector('.tool-calls-container');
            if (!container) return;

            if (data.tool_calls.length === 0) {
                container.innerHTML = '<div class="empty">No tool calls yet</div>';
            } else {
                let html = '';
                for (let i = 0; i < data.tool_calls.length; i++) {
                    const tool = data.tool_calls[i];
                    const errorClass = tool.ok ? '' : 'error';
                    const resultClass = tool.ok ? 'success' : 'error';
                    const resultHtml = tool.result_summary ?
                        `<div class="tool-call-result ${resultClass}">${escapeHtml(tool.result_summary)}</div>` : '';

                    html += `
                        <div class="tool-call ${tool.category} ${errorClass}" onclick="openToolModal(${i})">
                            <div class="tool-call-header">
                                <span class="icon">${tool.icon}</span>
                                <span class="name">${escapeHtml(tool.name)}</span>
                                <span class="turn-badge">T${tool.turn}</span>
                            </div>
                            ${resultHtml}
                        </div>
                    `;
                }
                container.innerHTML = html;
            }

            // Restore scroll position
            toolPanel.scrollTop = scrollPos;
        }

        function updateRightPanel(data) {
            const panels = document.querySelectorAll('.panel.half');
            const rightPanel = panels.length > 1 ? panels[1] : null;
            if (!rightPanel) return;

            const heading = rightPanel.querySelector('h2');
            const countBadge = rightPanel.querySelector('.count-badge');

            // Save scroll position
            const scrollPos = rightPanel.scrollTop;

            if (data.verbose_mode) {
                // Update game events
                heading.childNodes[0].textContent = 'Game Events ';
                if (countBadge) countBadge.textContent = data.game_events.length;

                const container = rightPanel.querySelector('.events-container');
                if (!container) return;

                if (data.game_events.length === 0) {
                    container.innerHTML = '<div class="empty">No game events yet</div>';
                } else {
                    let html = '';
                    for (const event of data.game_events) {
                        html += `
                            <div class="game-event">
                                <div class="event-type">${escapeHtml(event.event_type)}</div>
                                <div class="event-content">${escapeHtml(event.content)}</div>
                            </div>
                        `;
                    }
                    container.innerHTML = html;
                }
            } else {
                // Update notifications
                heading.childNodes[0].textContent = 'Notifications ';
                if (countBadge) countBadge.textContent = data.notifications.length;

                const container = rightPanel.querySelector('.notifications-container');
                if (!container) return;

                if (data.notifications.length === 0) {
                    container.innerHTML = '<div class="empty">No notifications yet</div>';
                } else {
                    let html = '';
                    for (const notif of data.notifications) {
                        const messageHtml = notif.message && notif.message !== notif.summary ?
                            `<div class="message">${escapeHtml(notif.message)}</div>` : '';
                        html += `
                            <div class="notification">
                                <div class="summary">${escapeHtml(notif.summary)}</div>
                                ${messageHtml}
                                <div class="meta">
                                    <span>T${notif.turn}</span>
                                    <span>Type ${notif.notif_type}</span>
                                </div>
                            </div>
                        `;
                    }
                    container.innerHTML = html;
                }
            }

            // Restore scroll position
            rightPanel.scrollTop = scrollPos;
        }

        function updateDebugPanel(data) {
            // This would be complex to update - skip for now since debug mode is rare
            // User can refresh page manually if needed
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Start auto-refresh
        refreshInterval = setInterval(refreshData, 5000);

        // Clean up on page unload
        window.addEventListener('beforeunload', () => {
            if (refreshInterval) {
                clearInterval(refreshInterval);
            }
        });
    </script>
</body>
</html>
"""


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


def parse_logs(debug_mode: bool = False, verbose_mode: bool = False, game_id: int | None = None) -> dict[str, Any]:
    """Parse JSONL logs and build conversation + tool call list.

    Args:
        debug_mode: Show debug diagnostics panel
        verbose_mode: Show game events instead of notifications
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
        "verbose_mode": verbose_mode,
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

    # Parse all messages from selected game file
    messages = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            debug.total_lines += 1
            line = line.strip()
            if not line:
                debug.empty_lines += 1
                continue
            try:
                msg = json.loads(line)
                messages.append(msg)
                # Track message types
                msg_type = msg.get("type", "(no type)")
                debug.type_counts[msg_type] += 1
            except json.JSONDecodeError as e:
                debug.parse_errors += 1
                logger.warning(f"JSON parse error on line {debug.total_lines}: {e}")
                continue

    # Build list of available games from scanned files
    available_games = []
    for gid, file_path, mtime in game_info:
        # Count messages in this game file (only for display)
        msg_count = sum(1 for line in open(file_path, "r") if line.strip())
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

        # Turn start - system prompt only (briefing comes via llm_request)
        if msg_type == "turn_start_messages":
            system_prompt = msg.get("system_prompt", "")

            if system_prompt:
                conversation.append({
                    "type": "message",
                    "role": "system",
                    "content": system_prompt,
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
            tokens = msg.get("total_tokens", 0) or 0

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

        # === GAME EVENTS (verbose mode) ===

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

    # Create JSON-safe version of tool_calls for modal
    data["tool_calls_json"] = json.dumps(data["tool_calls"])

    # Estimate cost (rough: $0.001 per 1K tokens for cheap models)
    data["estimated_cost"] = data["total_tokens"] * 0.000001

    if debug_mode:
        # Convert defaultdict to regular dict for JSON serialization
        debug.type_counts = dict(debug.type_counts)
        data["debug"] = debug.__dict__

    return data


@app.route("/")
def dashboard():
    debug_mode = request.args.get("debug") == "1"
    verbose_mode = request.args.get("verbose") == "1"
    game_id_str = request.args.get("game_id")
    game_id = int(game_id_str) if game_id_str else None
    data = parse_logs(debug_mode=debug_mode, verbose_mode=verbose_mode, game_id=game_id)
    return render_template_string(TEMPLATE, **data)


@app.route("/api/data")
def api_data():
    """JSON endpoint for programmatic access."""
    debug_mode = request.args.get("debug") == "1"
    verbose_mode = request.args.get("verbose") == "1"
    game_id_str = request.args.get("game_id")
    game_id = int(game_id_str) if game_id_str else None
    return parse_logs(debug_mode=debug_mode, verbose_mode=verbose_mode, game_id=game_id)


def main():
    print("╔══════════════════════════════════════════════════╗")
    print("║         Civ V LLM Dashboard                      ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  URL:      http://localhost:5000                 ║")
    print(f"║  Debug:    http://localhost:5000?debug=1         ║")
    print(f"║  Verbose:  http://localhost:5000?verbose=1       ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  Log dir:  {str(LOG_DIR):<37} ║")
    print("╚══════════════════════════════════════════════════╝")

    if not LOG_DIR.exists():
        logger.warning(f"Log directory does not exist yet: {LOG_DIR}")
    else:
        game_files = list(LOG_DIR.glob("game_*.jsonl"))
        logger.info(f"Found {len(game_files)} game log files in {LOG_DIR}")

    app.run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()
