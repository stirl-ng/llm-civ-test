"""
Flask Dashboard for Civilization V LLM Orchestrator

Provides a web interface for:
- Viewing logs with filtering
- Triggering MCP commands manually
- Monitoring game state
"""

import json
import logging
import os
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

from flask import Flask, Response, jsonify, render_template_string, request

from .mcp_server import AVAILABLE_TOOLS, CivMCPServer

# In-memory log buffer for real-time viewing
LOG_BUFFER_SIZE = 1000
_log_buffer: deque = deque(maxlen=LOG_BUFFER_SIZE)
_log_lock = Lock()


class DashboardLogHandler(logging.Handler):
    """Custom log handler that stores logs in memory for the dashboard."""

    def emit(self, record: logging.LogRecord):
        try:
            # Try to extract player_id from the message
            player_id = None
            raw_msg = record.getMessage()
            
            # Try to extract player_id from the message
            # Messages from DLL often contain JSON with player_id field
            # Use regex to find "player_id": <number> pattern (works for both single-line and multi-line JSON)
            try:
                match = re.search(r'"player_id"\s*:\s*(\d+)', raw_msg)
                if match:
                    player_id = int(match.group(1))
            except (ValueError, AttributeError):
                pass
            
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
                "raw_message": raw_msg,
                "player_id": player_id,
            }
            with _log_lock:
                _log_buffer.append(log_entry)
        except Exception:
            self.handleError(record)


def setup_dashboard_logging():
    """Add the dashboard log handler to capture logs."""
    handler = DashboardLogHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Add to root logger only - child loggers propagate up
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)


def get_logs(
    level_filter: Optional[str] = None,
    text_filter: Optional[str] = None,
    player_id_filter: Optional[int] = None,
    limit: int = 100,
) -> list[dict]:
    """Get logs from buffer with optional filtering."""
    with _log_lock:
        logs = list(_log_buffer)

    # Apply filters
    if level_filter and level_filter != "ALL":
        logs = [log for log in logs if log["level"] == level_filter]

    if text_filter:
        pattern = re.compile(re.escape(text_filter), re.IGNORECASE)
        logs = [log for log in logs if pattern.search(log["message"])]

    if player_id_filter is not None:
        logs = [log for log in logs if log.get("player_id") == player_id_filter]

    # Return most recent first, limited
    return list(reversed(logs))[:limit]


def read_log_file(limit: int = 500) -> list[dict]:
    """Read logs from the log file."""
    log_path = Path(__file__).resolve().parents[1] / "logs" / "orchestrator.log"
    logs = []

    if not log_path.exists():
        return logs

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]

        for line in lines:
            # Parse log format: [timestamp][level] message
            match = re.match(r"\[([^\]]+)\]\[([^\]]+)\] (.+)", line.strip())
            if match:
                message = match.group(3)
                # Try to extract player_id from message
                player_id = None
                player_id_match = re.search(r'"player_id"\s*:\s*(\d+)', message)
                if player_id_match:
                    try:
                        player_id = int(player_id_match.group(1))
                    except ValueError:
                        pass
                
                logs.append({
                    "timestamp": match.group(1),
                    "level": match.group(2),
                    "logger": "file",
                    "message": message,
                    "raw_message": message,
                    "player_id": player_id,
                })
            elif line.strip():
                # Try to extract player_id from unformatted line
                player_id = None
                player_id_match = re.search(r'"player_id"\s*:\s*(\d+)', line.strip())
                if player_id_match:
                    try:
                        player_id = int(player_id_match.group(1))
                    except ValueError:
                        pass
                
                logs.append({
                    "timestamp": "",
                    "level": "INFO",
                    "logger": "file",
                    "message": line.strip(),
                    "raw_message": line.strip(),
                    "player_id": player_id,
                })
    except Exception as e:
        logs.append({
            "timestamp": datetime.now().isoformat(),
            "level": "ERROR",
            "logger": "dashboard",
            "message": f"Error reading log file: {e}",
            "raw_message": str(e),
        })

    return logs


# HTML template for the dashboard
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Civ V LLM Dashboard</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
        }
        .header {
            background: #16213e;
            padding: 1rem 2rem;
            border-bottom: 2px solid #0f3460;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            color: #e94560;
            font-size: 1.5rem;
        }
        .status {
            display: flex;
            gap: 1rem;
            align-items: center;
        }
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #4ade80;
        }
        .status-indicator.disconnected {
            background: #ef4444;
        }
        .container {
            display: grid;
            grid-template-columns: 1fr 350px;
            gap: 1rem;
            padding: 1rem;
            height: calc(100vh - 70px);
        }
        .tabs {
            display: flex;
            background: #0f3460;
            border-bottom: 2px solid #1a4b8c;
        }
        .tab {
            padding: 0.75rem 1.5rem;
            cursor: pointer;
            background: transparent;
            border: none;
            color: #aaa;
            font-weight: 500;
            transition: all 0.2s;
        }
        .tab:hover {
            background: #1a4b8c;
            color: #eee;
        }
        .tab.active {
            background: #16213e;
            color: #e94560;
            border-bottom: 2px solid #e94560;
        }
        .tab-content {
            display: none;
        }
        .tab-content.active {
            display: block;
        }
        .panel {
            background: #16213e;
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .panel-header {
            background: #0f3460;
            padding: 0.75rem 1rem;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .panel-body {
            flex: 1;
            overflow-y: auto;
            padding: 1rem;
        }
        /* Log viewer styles */
        .log-filters {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }
        .log-filters select, .log-filters input {
            background: #1a1a2e;
            border: 1px solid #0f3460;
            color: #eee;
            padding: 0.5rem;
            border-radius: 4px;
        }
        .log-filters input {
            flex: 1;
            min-width: 200px;
        }
        .log-filters button {
            background: #e94560;
            border: none;
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 4px;
            cursor: pointer;
        }
        .log-filters button:hover {
            background: #d63050;
        }
        .log-entry {
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.85rem;
            padding: 0.4rem 0.6rem;
            border-radius: 4px;
            margin-bottom: 0.25rem;
            background: #1a1a2e;
            word-break: break-word;
        }
        .log-entry .timestamp {
            color: #888;
            margin-right: 0.5rem;
        }
        .log-entry .level {
            font-weight: 600;
            margin-right: 0.5rem;
            padding: 0.1rem 0.4rem;
            border-radius: 3px;
            font-size: 0.75rem;
        }
        .log-entry .level.INFO { background: #3b82f6; }
        .log-entry .level.DEBUG { background: #6b7280; }
        .log-entry .level.WARNING { background: #f59e0b; color: #000; }
        .log-entry .level.ERROR { background: #ef4444; }
        .log-entry .level.CRITICAL { background: #7c2d12; }
        /* Command panel styles */
        .command-section {
            margin-bottom: 1.5rem;
        }
        .command-section h3 {
            color: #e94560;
            font-size: 0.9rem;
            margin-bottom: 0.75rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid #0f3460;
        }
        .command-btn {
            display: block;
            width: 100%;
            background: #0f3460;
            border: 1px solid #1a4b8c;
            color: #eee;
            padding: 0.6rem 0.8rem;
            border-radius: 4px;
            cursor: pointer;
            text-align: left;
            margin-bottom: 0.5rem;
            font-size: 0.85rem;
            transition: all 0.2s;
        }
        .command-btn:hover {
            background: #1a4b8c;
            border-color: #2563eb;
        }
        .command-btn:active {
            transform: scale(0.98);
        }
        .command-btn.action {
            border-color: #e94560;
        }
        .command-btn.action:hover {
            background: #3d1a2e;
        }
        .command-result {
            background: #1a1a2e;
            border-radius: 4px;
            padding: 0.75rem;
            margin-top: 1rem;
            font-family: monospace;
            font-size: 0.8rem;
            max-height: 200px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .command-result.error {
            border-left: 3px solid #ef4444;
        }
        .command-result.success {
            border-left: 3px solid #4ade80;
        }
        /* State viewer */
        .state-summary {
            background: #1a1a2e;
            padding: 0.75rem;
            border-radius: 4px;
            font-size: 0.85rem;
        }
        .state-summary .label {
            color: #888;
        }
        .state-summary .value {
            color: #4ade80;
            font-weight: 600;
        }
        /* Auto-refresh toggle */
        .auto-refresh {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .toggle-switch {
            position: relative;
            width: 40px;
            height: 20px;
        }
        .toggle-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #374151;
            border-radius: 20px;
            transition: 0.3s;
        }
        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 14px;
            width: 14px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            border-radius: 50%;
            transition: 0.3s;
        }
        .toggle-switch input:checked + .toggle-slider {
            background-color: #4ade80;
        }
        .toggle-switch input:checked + .toggle-slider:before {
            transform: translateX(20px);
        }
        .empty-state {
            color: #666;
            text-align: center;
            padding: 2rem;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Civ V LLM Dashboard</h1>
        <div class="status">
            <span>Server Status:</span>
            <div class="status-indicator" id="statusIndicator"></div>
            <span id="statusText">Checking...</span>
        </div>
    </div>

    <div class="container">
        <div class="panel">
            <div class="panel-header">
                <span>Logs & Messages</span>
                <div class="auto-refresh">
                    <span>Auto-refresh</span>
                    <label class="toggle-switch">
                        <input type="checkbox" id="autoRefresh" checked>
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
            <div class="tabs">
                <button class="tab active" onclick="switchTab('python')">Python Logs</button>
                <button class="tab" onclick="switchTab('messages')">Message Log (JSONL)</button>
            </div>
            <div class="panel-body">
                <!-- Python Logs Tab -->
                <div id="pythonTab" class="tab-content active">
                    <div class="log-filters">
                        <select id="levelFilter">
                            <option value="ALL">All Levels</option>
                            <option value="DEBUG">DEBUG</option>
                            <option value="INFO">INFO</option>
                            <option value="WARNING">WARNING</option>
                            <option value="ERROR">ERROR</option>
                        </select>
                        <input type="text" id="textFilter" placeholder="Search logs...">
                        <input type="number" id="playerIdFilter" placeholder="Player ID" min="0" style="width: 120px;">
                        <button onclick="refreshLogs()">Refresh</button>
                        <button onclick="clearLogs()">Clear</button>
                    </div>
                    <div id="logContainer">
                        <div class="empty-state">Loading logs...</div>
                    </div>
                </div>
                
                <!-- Message Log Tab -->
                <div id="messagesTab" class="tab-content">
                    <div class="log-filters">
                        <select id="messageTypeFilter">
                            <option value="">All Types</option>
                            <option value="turn_start">Turn Start</option>
                            <option value="notification">Notification</option>
                            <option value="action_result">Action Result</option>
                            <option value="tool_call">Tool Call</option>
                            <option value="tool_result_get_notifications">Tool Result</option>
                        </select>
                        <select id="directionFilter">
                            <option value="">All Directions</option>
                            <option value="incoming">Incoming</option>
                            <option value="outgoing">Outgoing</option>
                        </select>
                        <input type="number" id="messageTurnFilter" placeholder="Min Turn" min="0" style="width: 120px;">
                        <input type="number" id="messagePlayerFilter" placeholder="Player ID" min="0" style="width: 120px;">
                        <input type="number" id="messageLimit" placeholder="Limit" value="100" min="1" max="1000" style="width: 100px;">
                        <button onclick="refreshMessages()">Refresh</button>
                        <button onclick="clearMessages()">Clear</button>
                    </div>
                    <div id="messageContainer">
                        <div class="empty-state">Loading messages...</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-header">
                <span>MCP Commands</span>
            </div>
            <div class="panel-body">
                <div class="command-section">
                    <h3>State Queries</h3>
                    <button class="command-btn" onclick="runCommand('get_game_state')">Get Game State</button>
                    <button class="command-btn" onclick="runCommand('get_cities')">Get Cities</button>
                    <button class="command-btn" onclick="runCommand('get_units')">Get Units</button>
                    <button class="command-btn" onclick="runCommand('get_tech_tree')">Get Tech Tree</button>
                    <button class="command-btn" onclick="runCommand('get_diplomacy')">Get Diplomacy</button>
                    <button class="command-btn" onclick="runCommand('get_available_choices')">Get Available Choices</button>
                    <button class="command-btn" onclick="runCommand('get_victory_progress')">Get Victory Progress</button>
                    <button class="command-btn" onclick="runCommand('get_resources')">Get Resources</button>
                    <button class="command-btn" onclick="runCommand('get_player_status')">Get Player Status</button>
                    <button class="command-btn" onclick="runCommand('get_demographics')">Get Demographics</button>
                    <button class="command-btn" onclick="runCommand('get_economic_overview')">Get Economic Overview</button>
                    <button class="command-btn" onclick="runCommand('get_notifications')">Get Notifications</button>
                    <button class="command-btn" onclick="runCommand('get_religion_overview')">Get Religion Overview</button>
                    <button class="command-btn" onclick="runCommand('get_tech_tree')">Get Tech Tree</button>
                    <button class="command-btn" onclick="runCommand('get_trade_route_overview')">Get Trade Route Overview</button>
                    <button class="command-btn" onclick="runCommand('get_victory_progress')">Get Victory Progress</button>
                    <button class="command-btn" onclick="runCommand('get_world_congress')">Get World Congress</button>
                </div>

                <div class="command-section">
                    <h3>Actions</h3>
                    <button class="command-btn action" onclick="endTurn()">End Turn</button>
                </div>

                <div class="command-section">
                    <h3>Server</h3>
                    <button class="command-btn" onclick="checkHealth()">Health Check</button>
                    <button class="command-btn" onclick="pingServer()">Ping</button>
                    <button class="command-btn" onclick="getTools()">List Tools</button>
                </div>

                <div id="commandResult" class="command-result" style="display: none;"></div>
            </div>
        </div>
    </div>

    <script>
        const MCP_BASE = 'http://localhost:8765';
        const DASHBOARD_BASE = '';
        let refreshInterval = null;

        // Log management
        async function refreshLogs() {
            const level = document.getElementById('levelFilter').value;
            const text = document.getElementById('textFilter').value;
            const playerId = document.getElementById('playerIdFilter').value;

            try {
                const params = new URLSearchParams();
                if (level !== 'ALL') params.set('level', level);
                if (text) params.set('text', text);
                if (playerId) params.set('player_id', playerId);
                params.set('limit', '200');

                const response = await fetch(`${DASHBOARD_BASE}/api/logs?${params}`);
                const data = await response.json();

                const container = document.getElementById('logContainer');
                if (data.logs.length === 0) {
                    container.innerHTML = '<div class="empty-state">No logs matching filter</div>';
                    return;
                }

                container.innerHTML = data.logs.map(log => `
                    <div class="log-entry">
                        <span class="timestamp">${log.timestamp}</span>
                        <span class="level ${log.level}">${log.level}</span>
                        ${escapeHtml(log.message)}
                    </div>
                `).join('');
            } catch (e) {
                console.error('Failed to fetch logs:', e);
            }
        }

        function clearLogs() {
            document.getElementById('logContainer').innerHTML = '<div class="empty-state">Logs cleared</div>';
        }

        // MCP command execution
        async function runCommand(toolName, args = {}) {
            const resultDiv = document.getElementById('commandResult');
            resultDiv.style.display = 'block';
            resultDiv.className = 'command-result';
            resultDiv.textContent = 'Running...';

            try {
                const response = await fetch(`${MCP_BASE}/tool`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tool: toolName, arguments: args})
                });
                const data = await response.json();
                resultDiv.className = 'command-result success';
                resultDiv.textContent = JSON.stringify(data, null, 2);
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
            }
        }

        // End turn with current turn number
        async function endTurn() {
            const resultDiv = document.getElementById('commandResult');
            resultDiv.style.display = 'block';
            resultDiv.className = 'command-result';
            resultDiv.textContent = 'Getting current turn...';

            try {
                // First, get the current turn number from session
                const sessionResponse = await fetch('/api/session');
                const sessionData = await sessionResponse.json();
                
                if (!sessionData.turn_number) {
                    resultDiv.className = 'command-result error';
                    resultDiv.textContent = 'Error: No active turn. Make sure the game is running and a turn has started.';
                    return;
                }

                // Now call end_turn with the current turn number
                resultDiv.textContent = `Ending turn ${sessionData.turn_number}...`;
                await runCommand('end_turn', {turn: sessionData.turn_number});
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
            }
        }

        async function checkHealth() {
            const resultDiv = document.getElementById('commandResult');
            resultDiv.style.display = 'block';

            try {
                const response = await fetch(`${MCP_BASE}/health`);
                const data = await response.json();
                resultDiv.className = 'command-result success';
                resultDiv.textContent = JSON.stringify(data, null, 2);
                updateStatus(true);
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                updateStatus(false);
            }
        }

        async function pingServer() {
            const resultDiv = document.getElementById('commandResult');
            resultDiv.style.display = 'block';
            resultDiv.className = 'command-result';
            resultDiv.textContent = 'Pinging...';

            try {
                const response = await fetch(`${MCP_BASE}/tool`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tool: 'ping', arguments: {}})
                });
                const data = await response.json();
                resultDiv.className = 'command-result success';
                resultDiv.textContent = JSON.stringify(data, null, 2);
                updateStatus(true);
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                updateStatus(false);
            }
        }

        async function getTools() {
            const resultDiv = document.getElementById('commandResult');
            resultDiv.style.display = 'block';

            try {
                const response = await fetch(`${MCP_BASE}/tools`);
                const data = await response.json();
                resultDiv.className = 'command-result success';
                resultDiv.textContent = JSON.stringify(data, null, 2);
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
            }
        }

        function updateStatus(connected) {
            const indicator = document.getElementById('statusIndicator');
            const text = document.getElementById('statusText');

            if (connected) {
                indicator.classList.remove('disconnected');
                text.textContent = 'Connected';
            } else {
                indicator.classList.add('disconnected');
                text.textContent = 'Disconnected';
            }
        }

        // Auto-refresh
        function setupAutoRefresh() {
            const checkbox = document.getElementById('autoRefresh');

            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    refreshInterval = setInterval(() => {
                        const activeTab = document.querySelector('.tab-content.active');
                        if (activeTab && activeTab.id === 'pythonTab') {
                            refreshLogs();
                        } else if (activeTab && activeTab.id === 'messagesTab') {
                            refreshMessages();
                        }
                    }, 2000);
                } else {
                    clearInterval(refreshInterval);
                }
            });

            // Start auto-refresh
            if (checkbox.checked) {
                refreshInterval = setInterval(() => {
                    const activeTab = document.querySelector('.tab-content.active');
                    if (activeTab && activeTab.id === 'pythonTab') {
                        refreshLogs();
                    } else if (activeTab && activeTab.id === 'messagesTab') {
                        refreshMessages();
                    }
                }, 2000);
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Tab switching
        function switchTab(tabName) {
            // Update tab buttons
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            event.target.classList.add('active');
            
            // Update tab content
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            if (tabName === 'python') {
                document.getElementById('pythonTab').classList.add('active');
            } else {
                document.getElementById('messagesTab').classList.add('active');
                refreshMessages();
            }
        }

        // Message log management
        async function refreshMessages() {
            const type = document.getElementById('messageTypeFilter').value;
            const direction = document.getElementById('directionFilter').value;
            const minTurn = document.getElementById('messageTurnFilter').value;
            const playerId = document.getElementById('messagePlayerFilter').value;
            const limit = document.getElementById('messageLimit').value || 100;

            try {
                const params = new URLSearchParams();
                if (type) params.set('type', type);
                if (direction) params.set('direction', direction);
                if (minTurn) params.set('min_turn', minTurn);
                if (playerId) params.set('player_id', playerId);
                params.set('limit', limit);

                const response = await fetch(`${DASHBOARD_BASE}/api/messages?${params}`);
                const data = await response.json();

                const container = document.getElementById('messageContainer');
                if (data.messages.length === 0) {
                    container.innerHTML = '<div class="empty-state">No messages matching filter</div>';
                    return;
                }

                container.innerHTML = data.messages.map(msg => {
                    const timestamp = msg.timestamp ? new Date(msg.timestamp * 1000).toISOString() : 'N/A';
                    const direction = msg.direction || 'unknown';
                    const type = msg.type || 'unknown';
                    const jsonStr = JSON.stringify(msg, null, 2);
                    
                    let chevron = '';
                    let chevronColor = '';
                    if (direction === 'incoming') {
                        chevron = '◀';
                        chevronColor = '#22c55e';
                    } else if (direction === 'outgoing') {
                        chevron = '▶';
                        chevronColor = '#ef4444';
                    }
                    
                    return `
                        <div class="log-entry">
                            <span class="timestamp">${timestamp}</span>
                            <span class="level ${direction}">
                                ${chevron ? `<span style="color: ${chevronColor}; font-size: 1.2em; margin-right: 0.25rem;">${chevron}</span>` : ''}${direction}
                            </span>
                            <span class="level" style="background: #6b7280; margin-left: 0.5rem;">${type}</span>
                            <details open style="margin-top: 0.5rem;">
                                <summary style="cursor: pointer; color: #d1d5db;">View JSON</summary>
                                <pre style="background: #0f3460; padding: 0.5rem; margin-top: 0.5rem; border-radius: 4px; overflow-x: auto; font-size: 0.75rem;">${escapeHtml(jsonStr)}</pre>
                            </details>
                        </div>
                    `;
                }).join('');
            } catch (e) {
                console.error('Failed to fetch messages:', e);
                document.getElementById('messageContainer').innerHTML = '<div class="empty-state">Error loading messages</div>';
            }
        }

        function clearMessages() {
            document.getElementById('messageContainer').innerHTML = '<div class="empty-state">Messages cleared</div>';
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            refreshLogs();
            checkHealth();
            setupAutoRefresh();

            // Filter on Enter key
            document.getElementById('textFilter').addEventListener('keyup', (e) => {
                if (e.key === 'Enter') refreshLogs();
            });

            // Filter on level change
            document.getElementById('levelFilter').addEventListener('change', refreshLogs);
            
            // Message filter handlers
            document.getElementById('messageTypeFilter').addEventListener('change', refreshMessages);
            document.getElementById('directionFilter').addEventListener('change', refreshMessages);
            document.getElementById('messageTurnFilter').addEventListener('keyup', (e) => {
                if (e.key === 'Enter') refreshMessages();
            });
            document.getElementById('messagePlayerFilter').addEventListener('keyup', (e) => {
                if (e.key === 'Enter') refreshMessages();
            });
        });
    </script>
</body>
</html>
"""


def create_dashboard_app(
    mcp_server: Optional[CivMCPServer] = None,
    state_processor: Optional["StateProcessor"] = None
) -> Flask:
    """Create and configure the Flask dashboard application.

    Args:
        mcp_server: Optional MCP server instance for tool execution
        state_processor: Optional StateProcessor for session tracking (game_id, session_id)
    """
    app = Flask(__name__)
    app.config["mcp_server"] = mcp_server
    app.config["state_processor"] = state_processor

    @app.route("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/logs")
    def api_logs():
        level_filter = request.args.get("level")
        text_filter = request.args.get("text")
        player_id_filter = request.args.get("player_id")
        limit = int(request.args.get("limit", 100))
        source = request.args.get("source", "memory")  # 'memory' or 'file'

        # Parse player_id filter if provided
        player_id = None
        if player_id_filter:
            try:
                player_id = int(player_id_filter)
            except ValueError:
                pass  # Invalid player_id, ignore filter

        if source == "file":
            logs = read_log_file(limit)
            # Apply filters
            if level_filter and level_filter != "ALL":
                logs = [log for log in logs if log["level"] == level_filter]
            if text_filter:
                pattern = re.compile(re.escape(text_filter), re.IGNORECASE)
                logs = [log for log in logs if pattern.search(log["message"])]
            if player_id is not None:
                logs = [log for log in logs if log.get("player_id") == player_id]
            logs = list(reversed(logs))[:limit]
        else:
            logs = get_logs(level_filter, text_filter, player_id, limit)

        return jsonify({"logs": logs, "count": len(logs)})

    @app.route("/api/state")
    def api_state():
        mcp = app.config.get("mcp_server")
        if mcp and mcp.current_state:
            return jsonify(mcp.current_state)
        return jsonify({"error": "No state available"})

    @app.route("/api/tools")
    def api_tools():
        return jsonify({"tools": AVAILABLE_TOOLS})

    @app.route("/api/session")
    def api_session():
        """Get current game and session info."""
        state_processor = app.config.get("state_processor")
        mcp = app.config.get("mcp_server")

        game_id = None
        session_id = None
        turn_number = None
        turn_active = False

        if state_processor:
            game_id = state_processor.current_game_id
            session_id = state_processor.current_session_id

        if mcp:
            turn_number = mcp.turn_number
            turn_active = mcp.turn_active

        return jsonify({
            "game_id": game_id,
            "session_id": session_id,
            "turn_number": turn_number,
            "turn_active": turn_active,
            "connected": state_processor is not None
        })

    @app.route("/api/messages")
    def api_messages():
        """Get messages from JSONL log with optional filters."""
        from .game_logger import GameLogger

        message_type = request.args.get("type")
        direction = request.args.get("direction")
        min_turn = request.args.get("min_turn", type=int)
        player_id = request.args.get("player_id", type=int)
        game_id = request.args.get("game_id", type=int)
        session_id = request.args.get("session_id", type=int)
        current_game_only = request.args.get("current_game", type=bool, default=False)
        limit = int(request.args.get("limit", 100))

        # Cap limit at 1000
        limit = min(limit, 1000)

        # If current_game_only and no explicit game_id, use current game from state_processor
        state_processor = app.config.get("state_processor")
        if current_game_only and game_id is None and state_processor:
            game_id = state_processor.current_game_id

        # Get messages from logger
        game_logger = GameLogger()
        messages = game_logger.get_messages(
            message_type=message_type,
            min_turn=min_turn,
            player_id=player_id,
            game_id=game_id,
            session_id=session_id
        )

        # Filter by direction if specified
        if direction:
            messages = [msg for msg in messages if msg.get("direction") == direction]

        # Return most recent messages first, limited
        messages = list(reversed(messages))[:limit]

        return jsonify({
            "messages": messages,
            "count": len(messages),
            "game_id": game_id,
            "session_id": session_id,
            "filters": {
                "type": message_type,
                "direction": direction,
                "min_turn": min_turn,
                "player_id": player_id,
                "game_id": game_id,
                "session_id": session_id,
                "current_game_only": current_game_only,
                "limit": limit
            }
        })

    return app


def run_dashboard(
    host: str = "0.0.0.0",
    port: int = 5000,
    mcp_server: Optional[CivMCPServer] = None,
    state_processor: Optional["StateProcessor"] = None,
    debug: bool = False,
):
    """Run the Flask dashboard server.

    Args:
        host: Host to bind to
        port: Port to bind to
        mcp_server: Optional MCP server instance
        state_processor: Optional StateProcessor for session tracking
        debug: Enable debug mode
    """
    setup_dashboard_logging()
    app = create_dashboard_app(mcp_server, state_processor)

    print(f"Dashboard running at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    import sys

    from .logging_setup import setup_logging

    setup_logging()

    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    run_dashboard(host, port, debug=True)
