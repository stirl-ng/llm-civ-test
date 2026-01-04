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
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
                "raw_message": record.getMessage(),
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
                logs.append({
                    "timestamp": match.group(1),
                    "level": match.group(2),
                    "logger": "file",
                    "message": match.group(3),
                    "raw_message": match.group(3),
                })
            elif line.strip():
                logs.append({
                    "timestamp": "",
                    "level": "INFO",
                    "logger": "file",
                    "message": line.strip(),
                    "raw_message": line.strip(),
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
                <span>Logs</span>
                <div class="auto-refresh">
                    <span>Auto-refresh</span>
                    <label class="toggle-switch">
                        <input type="checkbox" id="autoRefresh" checked>
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
            <div class="panel-body">
                <div class="log-filters">
                    <select id="levelFilter">
                        <option value="ALL">All Levels</option>
                        <option value="DEBUG">DEBUG</option>
                        <option value="INFO">INFO</option>
                        <option value="WARNING">WARNING</option>
                        <option value="ERROR">ERROR</option>
                    </select>
                    <input type="text" id="textFilter" placeholder="Search logs...">
                    <button onclick="refreshLogs()">Refresh</button>
                    <button onclick="clearLogs()">Clear</button>
                </div>
                <div id="logContainer">
                    <div class="empty-state">Loading logs...</div>
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
                    <button class="command-btn" onclick="runCommand('format_state')">Format State (Human Readable)</button>
                </div>

                <div class="command-section">
                    <h3>Actions</h3>
                    <button class="command-btn action" onclick="runCommand('end_turn')">End Turn</button>
                </div>

                <div class="command-section">
                    <h3>Server</h3>
                    <button class="command-btn" onclick="checkHealth()">Health Check</button>
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

            try {
                const params = new URLSearchParams();
                if (level !== 'ALL') params.set('level', level);
                if (text) params.set('text', text);
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
                    refreshInterval = setInterval(refreshLogs, 2000);
                } else {
                    clearInterval(refreshInterval);
                }
            });

            // Start auto-refresh
            if (checkbox.checked) {
                refreshInterval = setInterval(refreshLogs, 2000);
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
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
        });
    </script>
</body>
</html>
"""


def create_dashboard_app(mcp_server: Optional[CivMCPServer] = None) -> Flask:
    """Create and configure the Flask dashboard application."""
    app = Flask(__name__)
    app.config["mcp_server"] = mcp_server

    @app.route("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/logs")
    def api_logs():
        level_filter = request.args.get("level")
        text_filter = request.args.get("text")
        limit = int(request.args.get("limit", 100))
        source = request.args.get("source", "memory")  # 'memory' or 'file'

        if source == "file":
            logs = read_log_file(limit)
            # Apply filters
            if level_filter and level_filter != "ALL":
                logs = [log for log in logs if log["level"] == level_filter]
            if text_filter:
                pattern = re.compile(re.escape(text_filter), re.IGNORECASE)
                logs = [log for log in logs if pattern.search(log["message"])]
            logs = list(reversed(logs))[:limit]
        else:
            logs = get_logs(level_filter, text_filter, limit)

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

    return app


def run_dashboard(
    host: str = "0.0.0.0",
    port: int = 5000,
    mcp_server: Optional[CivMCPServer] = None,
    debug: bool = False,
):
    """Run the Flask dashboard server."""
    setup_dashboard_logging()
    app = create_dashboard_app(mcp_server)

    print(f"Dashboard running at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    run_dashboard(host, port, debug=True)
