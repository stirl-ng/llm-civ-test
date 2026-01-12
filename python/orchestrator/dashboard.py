"""
Flask Dashboard for Civilization V LLM Orchestrator

Provides a web interface for:
- Viewing logs with filtering
- Triggering MCP commands manually
- Monitoring game state
"""

import json
import re
from datetime import datetime
from typing import Optional

from flask import Flask, jsonify, render_template_string, request

from .mcp_server import CivMCPServer


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
        /* Unit action panel */
        .unit-action-panel {
            background: #1a1a2e;
            border-radius: 4px;
            padding: 0.75rem;
            margin-bottom: 1rem;
        }
        .unit-action-panel select, .unit-action-panel input {
            width: 100%;
            background: #0f3460;
            border: 1px solid #1a4b8c;
            color: #eee;
            padding: 0.5rem;
            border-radius: 4px;
            margin-bottom: 0.5rem;
            font-size: 0.85rem;
        }
        .unit-action-panel select:disabled {
            opacity: 0.5;
        }
        .unit-action-panel label {
            display: block;
            color: #888;
            font-size: 0.75rem;
            margin-bottom: 0.25rem;
        }
        .unit-info {
            background: #0f3460;
            padding: 0.5rem;
            border-radius: 4px;
            margin-bottom: 0.5rem;
            font-size: 0.8rem;
        }
        .unit-info .unit-name {
            color: #4ade80;
            font-weight: 600;
        }
        .unit-info .unit-stats {
            color: #888;
            margin-top: 0.25rem;
        }
        .param-inputs {
            margin: 0.5rem 0;
        }
        .param-inputs input {
            margin-bottom: 0.25rem;
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
            <div class="panel-body">
                <div class="log-filters">
                    <select id="messageTypeFilter">
                        <option value="">All Types</option>
                        <option value="turn_start">Turn Start</option>
                        <option value="turn_complete">Turn Complete</option>
                        <option value="notification">Notification</option>
                        <option value="action_result">Action Result</option>
                        <option value="tool_call">Tool Call</option>
                        <option value="note">Note</option>
                    </select>
                    <select id="directionFilter">
                        <option value="">All Directions</option>
                        <option value="incoming">Incoming (from DLL)</option>
                        <option value="outgoing">Outgoing (to DLL)</option>
                    </select>
                    <input type="number" id="messageTurnFilter" placeholder="Min Turn" min="0" style="width: 100px;">
                    <input type="number" id="messageLimit" placeholder="Limit" value="100" min="1" max="1000" style="width: 80px;">
                    <button onclick="refreshMessages()">Refresh</button>
                </div>
                <div id="messageContainer">
                    <div class="empty-state">Loading messages...</div>
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
                    <h3>Unit Actions</h3>
                    <div class="unit-action-panel">
                        <button class="command-btn" onclick="loadUnits()" style="margin-bottom: 0.75rem;">Load Units</button>

                        <label>Select Unit</label>
                        <select id="unitSelect" onchange="onUnitSelected()" disabled>
                            <option value="">-- Load units first --</option>
                        </select>

                        <div id="unitInfo" class="unit-info" style="display: none;"></div>

                        <label>Action</label>
                        <select id="actionSelect" onchange="onActionSelected()" disabled>
                            <option value="">-- Select unit first --</option>
                        </select>

                        <div id="paramInputs" class="param-inputs"></div>

                        <button class="command-btn action" id="sendActionBtn" onclick="sendUnitAction()" disabled>Send Action</button>
                    </div>
                </div>

                <div class="command-section">
                    <h3>City Production</h3>
                    <div class="unit-action-panel">
                        <button class="command-btn" onclick="loadCities()" style="margin-bottom: 0.75rem;">Load Cities</button>

                        <label>Select City</label>
                        <select id="citySelect" onchange="onCitySelected()" disabled>
                            <option value="">-- Load cities first --</option>
                        </select>

                        <div id="cityInfo" class="unit-info" style="display: none;"></div>

                        <label>Production Type</label>
                        <select id="prodTypeSelect" onchange="onProdTypeSelected()" disabled>
                            <option value="">-- Select city first --</option>
                        </select>

                        <label>Item</label>
                        <select id="prodItemSelect" disabled>
                            <option value="">-- Select type first --</option>
                        </select>

                        <button class="command-btn action" id="setProdBtn" onclick="setProduction()" disabled style="margin-top: 0.5rem;">Set Production</button>
                    </div>
                </div>

                <div class="command-section">
                    <h3>Research</h3>
                    <div class="unit-action-panel">
                        <button class="command-btn" onclick="loadTechs()" style="margin-bottom: 0.75rem;">Load Available Techs</button>

                        <label>Select Technology</label>
                        <select id="techSelect" disabled>
                            <option value="">-- Load techs first --</option>
                        </select>

                        <button class="command-btn action" id="chooseTechBtn" onclick="chooseTech()" disabled style="margin-top: 0.5rem;">Choose Tech</button>
                    </div>
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
        let hideResultTimeout = null;

        function scheduleAutoHide() {
            if (hideResultTimeout) {
                clearTimeout(hideResultTimeout);
            }
            hideResultTimeout = setTimeout(() => {
                const resultDiv = document.getElementById('commandResult');
                resultDiv.style.display = 'none';
            }, 5000);
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
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
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
                    scheduleAutoHide();
                    return;
                }

                // Now call end_turn with the current turn number
                resultDiv.textContent = `Ending turn ${sessionData.turn_number}...`;
                await runCommand('end_turn', {turn: sessionData.turn_number});
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
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
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                updateStatus(false);
                scheduleAutoHide();
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
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                updateStatus(false);
                scheduleAutoHide();
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
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
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
                    refreshInterval = setInterval(refreshMessages, 2000);
                } else {
                    clearInterval(refreshInterval);
                }
            });

            // Start auto-refresh
            if (checkbox.checked) {
                refreshInterval = setInterval(refreshMessages, 2000);
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Message log management
        async function refreshMessages() {
            const type = document.getElementById('messageTypeFilter').value;
            const direction = document.getElementById('directionFilter').value;
            const turnNumber = document.getElementById('messageTurnFilter').value;
            const limit = document.getElementById('messageLimit').value || 100;

            try {
                const params = new URLSearchParams();
                if (type) params.set('type', type);
                if (direction) params.set('direction', direction);
                if (turnNumber) params.set('turn_number', turnNumber);
                params.set('limit', limit);

                const response = await fetch(`${DASHBOARD_BASE}/api/messages?${params}`);
                const data = await response.json();

                const container = document.getElementById('messageContainer');
                if (data.messages.length === 0) {
                    container.innerHTML = '<div class="empty-state">No messages matching filter</div>';
                    return;
                }

                container.innerHTML = data.messages.map(msg => {
                    const timestamp = msg.timestamp ? new Date(msg.timestamp).toISOString() : 'N/A';
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

        // Unit action management
        let loadedUnits = [];
        const UNIT_ACTIONS = {
            'move_unit': { label: 'Move', params: [{name: 'to', type: 'coords', label: 'Target [x,y]'}] },
            'unit_fortify': { label: 'Fortify', params: [] },
            'unit_sleep': { label: 'Sleep', params: [] },
            'unit_skip': { label: 'Skip Turn', params: [] },
            'unit_alert': { label: 'Alert', params: [] },
            'unit_heal': { label: 'Heal', params: [] },
            'unit_pillage': { label: 'Pillage', params: [] },
            'unit_delete': { label: 'Delete/Disband', params: [] },
            'unit_found_city': { label: 'Found City', params: [] },
            'unit_ranged_attack': { label: 'Ranged Attack', params: [{name: 'target', type: 'coords', label: 'Target [x,y]'}] },
            'unit_build': { label: 'Build', params: [{name: 'build_type', type: 'int', label: 'Build Type ID'}] },
            'unit_auto_explore': { label: 'Auto Explore', params: [] },
            'select_unit': { label: 'Select (UI)', params: [] },
        };

        async function loadUnits() {
            const resultDiv = document.getElementById('commandResult');
            resultDiv.style.display = 'block';
            resultDiv.className = 'command-result';
            resultDiv.textContent = 'Loading units...';

            try {
                const response = await fetch(`${MCP_BASE}/tool`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tool: 'get_units', arguments: {}})
                });
                const data = await response.json();

                // HTTP server wraps in {status, result}
                const result = data.result || data;

                if (data.status === 'error' || result.error) {
                    resultDiv.className = 'command-result error';
                    resultDiv.textContent = `Error: ${result.error || JSON.stringify(result)}`;
                    scheduleAutoHide();
                    return;
                }

                // Extract units from response
                loadedUnits = result.units || [];

                const unitSelect = document.getElementById('unitSelect');
                unitSelect.innerHTML = '<option value="">-- Select a unit --</option>';

                loadedUnits.forEach(unit => {
                    const opt = document.createElement('option');
                    opt.value = unit.id;
                    const name = unit.unit_type_name || unit.name || unit.type || 'Unit';
                    opt.textContent = `[${unit.id}] ${name} @ (${unit.x}, ${unit.y})`;
                    unitSelect.appendChild(opt);
                });

                unitSelect.disabled = false;
                resultDiv.className = 'command-result success';
                resultDiv.textContent = `Loaded ${loadedUnits.length} units`;
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
            }
        }

        function onUnitSelected() {
            const unitSelect = document.getElementById('unitSelect');
            const actionSelect = document.getElementById('actionSelect');
            const unitInfo = document.getElementById('unitInfo');
            const sendBtn = document.getElementById('sendActionBtn');

            const unitId = parseInt(unitSelect.value);
            const unit = loadedUnits.find(u => u.id === unitId);

            if (!unit) {
                unitInfo.style.display = 'none';
                actionSelect.disabled = true;
                actionSelect.innerHTML = '<option value="">-- Select unit first --</option>';
                sendBtn.disabled = true;
                return;
            }

            // Show unit info
            const unitName = unit.unit_type_name || unit.name || unit.type || 'Unit';
            const moves = unit.moves_remaining ?? unit.moves ?? 'N/A';
            const hp = unit.max_hit_points != null ? (unit.max_hit_points - (unit.damage || 0)) : (unit.hp ?? 'N/A');
            const maxHp = unit.max_hit_points ?? unit.max_hp ?? 'N/A';

            unitInfo.style.display = 'block';
            unitInfo.innerHTML = `
                <div class="unit-name">${unitName}</div>
                <div class="unit-stats">
                    ID: ${unit.id} | Pos: (${unit.x}, ${unit.y}) | Moves: ${moves} | HP: ${hp}/${maxHp}
                </div>
            `;

            // Populate actions
            actionSelect.innerHTML = '<option value="">-- Select action --</option>';
            for (const [actionType, actionDef] of Object.entries(UNIT_ACTIONS)) {
                const opt = document.createElement('option');
                opt.value = actionType;
                opt.textContent = actionDef.label;
                actionSelect.appendChild(opt);
            }
            actionSelect.disabled = false;
            document.getElementById('paramInputs').innerHTML = '';
            sendBtn.disabled = true;
        }

        function onActionSelected() {
            const actionSelect = document.getElementById('actionSelect');
            const paramInputs = document.getElementById('paramInputs');
            const sendBtn = document.getElementById('sendActionBtn');

            const actionType = actionSelect.value;
            const actionDef = UNIT_ACTIONS[actionType];

            if (!actionDef) {
                paramInputs.innerHTML = '';
                sendBtn.disabled = true;
                return;
            }

            // Generate param inputs
            if (actionDef.params.length === 0) {
                paramInputs.innerHTML = '<div style="color: #888; font-size: 0.8rem;">No parameters needed</div>';
            } else {
                paramInputs.innerHTML = actionDef.params.map(p => {
                    if (p.type === 'coords') {
                        return `
                            <label>${p.label}</label>
                            <div style="display: flex; gap: 0.5rem;">
                                <input type="number" id="param_${p.name}_x" placeholder="X" style="flex: 1;">
                                <input type="number" id="param_${p.name}_y" placeholder="Y" style="flex: 1;">
                            </div>
                        `;
                    } else {
                        return `
                            <label>${p.label}</label>
                            <input type="${p.type === 'int' ? 'number' : 'text'}" id="param_${p.name}" placeholder="${p.label}">
                        `;
                    }
                }).join('');
            }

            sendBtn.disabled = false;
        }

        async function sendUnitAction() {
            const unitSelect = document.getElementById('unitSelect');
            const actionSelect = document.getElementById('actionSelect');
            const resultDiv = document.getElementById('commandResult');

            const unitId = parseInt(unitSelect.value);
            const actionType = actionSelect.value;
            const actionDef = UNIT_ACTIONS[actionType];

            if (!unitId || !actionType || !actionDef) {
                resultDiv.style.display = 'block';
                resultDiv.className = 'command-result error';
                resultDiv.textContent = 'Please select a unit and action';
                scheduleAutoHide();
                return;
            }

            // Build action object
            const action = { kind: actionType, unit_id: unitId };

            // Collect params
            for (const p of actionDef.params) {
                if (p.type === 'coords') {
                    const x = parseInt(document.getElementById(`param_${p.name}_x`).value);
                    const y = parseInt(document.getElementById(`param_${p.name}_y`).value);
                    if (isNaN(x) || isNaN(y)) {
                        resultDiv.style.display = 'block';
                        resultDiv.className = 'command-result error';
                        resultDiv.textContent = `Please enter valid coordinates for ${p.label}`;
                        scheduleAutoHide();
                        return;
                    }
                    action[p.name] = [x, y];
                } else if (p.type === 'int') {
                    const val = parseInt(document.getElementById(`param_${p.name}`).value);
                    if (isNaN(val)) {
                        resultDiv.style.display = 'block';
                        resultDiv.className = 'command-result error';
                        resultDiv.textContent = `Please enter a valid number for ${p.label}`;
                        scheduleAutoHide();
                        return;
                    }
                    action[p.name] = val;
                } else {
                    action[p.name] = document.getElementById(`param_${p.name}`).value;
                }
            }

            resultDiv.style.display = 'block';
            resultDiv.className = 'command-result';
            resultDiv.textContent = `Sending ${actionType}...`;

            try {
                const response = await fetch(`${MCP_BASE}/tool`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tool: 'send_action', arguments: {action: action}})
                });
                const data = await response.json();
                const result = data.result || data;
                const isError = data.status === 'error' || result.success === false || result.error;
                resultDiv.className = isError ? 'command-result error' : 'command-result success';
                resultDiv.textContent = JSON.stringify(result, null, 2);
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
            }
        }

        // City production management
        let loadedCities = [];
        const PROD_TYPES = {
            0: { label: 'Units', key: 'trainable_units' },
            1: { label: 'Buildings', key: 'constructable_buildings' },
            2: { label: 'Projects/Wonders', key: 'creatable_projects' },
            3: { label: 'Processes', key: 'maintainable_processes' }
        };

        async function loadCities() {
            const resultDiv = document.getElementById('commandResult');
            resultDiv.style.display = 'block';
            resultDiv.className = 'command-result';
            resultDiv.textContent = 'Loading cities...';

            try {
                const response = await fetch(`${MCP_BASE}/tool`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tool: 'get_cities', arguments: {}})
                });
                const data = await response.json();
                const result = data.result || data;

                if (data.status === 'error' || result.error) {
                    resultDiv.className = 'command-result error';
                    resultDiv.textContent = `Error: ${result.error || JSON.stringify(result)}`;
                    scheduleAutoHide();
                    return;
                }

                loadedCities = result.cities || [];

                const citySelect = document.getElementById('citySelect');
                citySelect.innerHTML = '<option value="">-- Select a city --</option>';

                loadedCities.forEach(city => {
                    const opt = document.createElement('option');
                    opt.value = city.id;
                    opt.textContent = `[${city.id}] ${city.name} (Pop: ${city.population})`;
                    citySelect.appendChild(opt);
                });

                citySelect.disabled = false;
                resultDiv.className = 'command-result success';
                resultDiv.textContent = `Loaded ${loadedCities.length} cities`;
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
            }
        }

        // Cache for city production options (keyed by city_id)
        let cityProductionCache = {};

        async function onCitySelected() {
            const citySelect = document.getElementById('citySelect');
            const prodTypeSelect = document.getElementById('prodTypeSelect');
            const prodItemSelect = document.getElementById('prodItemSelect');
            const cityInfo = document.getElementById('cityInfo');
            const setProdBtn = document.getElementById('setProdBtn');
            const resultDiv = document.getElementById('commandResult');

            const cityId = parseInt(citySelect.value);
            const city = loadedCities.find(c => c.id === cityId);

            if (!city) {
                cityInfo.style.display = 'none';
                prodTypeSelect.disabled = true;
                prodTypeSelect.innerHTML = '<option value="">-- Select city first --</option>';
                prodItemSelect.disabled = true;
                prodItemSelect.innerHTML = '<option value="">-- Select type first --</option>';
                setProdBtn.disabled = true;
                return;
            }

            // Show city info
            const currentProd = city.current_production || city.producing || 'None';
            cityInfo.style.display = 'block';
            cityInfo.innerHTML = `
                <div class="unit-name">${city.name}</div>
                <div class="unit-stats">
                    Pop: ${city.population} | Production: ${currentProd}
                </div>
            `;

            // Reset dropdowns while loading
            prodTypeSelect.innerHTML = '<option value="">Loading production options...</option>';
            prodTypeSelect.disabled = true;
            prodItemSelect.innerHTML = '<option value="">-- Select type first --</option>';
            prodItemSelect.disabled = true;
            setProdBtn.disabled = true;

            // Fetch production options for this city
            try {
                const response = await fetch(`${MCP_BASE}/tool`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tool: 'get_city_production', arguments: {city_id: cityId}})
                });
                const data = await response.json();
                const result = data.result || data;

                if (data.status === 'error' || result.error) {
                    prodTypeSelect.innerHTML = '<option value="">-- Error loading --</option>';
                    resultDiv.style.display = 'block';
                    resultDiv.className = 'command-result error';
                    resultDiv.textContent = `Error: ${result.error || JSON.stringify(result)}`;
                    scheduleAutoHide();
                    return;
                }

                // Cache the production options
                cityProductionCache[cityId] = result;

                // Populate production types
                prodTypeSelect.innerHTML = '<option value="">-- Select type --</option>';
                for (const [typeId, typeDef] of Object.entries(PROD_TYPES)) {
                    const items = result[typeDef.key] || [];
                    if (items.length > 0 || typeId == 3) { // Always show processes
                        const opt = document.createElement('option');
                        opt.value = typeId;
                        opt.textContent = `${typeDef.label} (${items.length})`;
                        prodTypeSelect.appendChild(opt);
                    }
                }
                prodTypeSelect.disabled = false;
            } catch (e) {
                prodTypeSelect.innerHTML = '<option value="">-- Error loading --</option>';
                resultDiv.style.display = 'block';
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
            }
        }

        function onProdTypeSelected() {
            const citySelect = document.getElementById('citySelect');
            const prodTypeSelect = document.getElementById('prodTypeSelect');
            const prodItemSelect = document.getElementById('prodItemSelect');
            const setProdBtn = document.getElementById('setProdBtn');

            const cityId = parseInt(citySelect.value);
            const orderType = parseInt(prodTypeSelect.value);

            // Use cached production options
            const cityProd = cityProductionCache[cityId];

            if (!cityProd || isNaN(orderType)) {
                prodItemSelect.innerHTML = '<option value="">-- Select type first --</option>';
                prodItemSelect.disabled = true;
                setProdBtn.disabled = true;
                return;
            }

            const typeDef = PROD_TYPES[orderType];
            const items = cityProd[typeDef.key] || [];

            prodItemSelect.innerHTML = '<option value="">-- Select item --</option>';
            items.forEach(item => {
                const opt = document.createElement('option');
                opt.value = item.id;
                const turns = item.turns ? ` (${item.turns} turns)` : '';
                opt.textContent = `${item.name}${turns}`;
                prodItemSelect.appendChild(opt);
            });

            prodItemSelect.disabled = items.length === 0;
            setProdBtn.disabled = true;

            // Enable button when item is selected
            prodItemSelect.onchange = () => {
                setProdBtn.disabled = !prodItemSelect.value;
            };
        }

        async function setProduction() {
            const citySelect = document.getElementById('citySelect');
            const prodTypeSelect = document.getElementById('prodTypeSelect');
            const prodItemSelect = document.getElementById('prodItemSelect');
            const resultDiv = document.getElementById('commandResult');

            const cityId = parseInt(citySelect.value);
            const orderType = parseInt(prodTypeSelect.value);
            const itemId = parseInt(prodItemSelect.value);

            if (isNaN(cityId) || isNaN(orderType) || isNaN(itemId)) {
                resultDiv.style.display = 'block';
                resultDiv.className = 'command-result error';
                resultDiv.textContent = 'Please select city, type, and item';
                scheduleAutoHide();
                return;
            }

            resultDiv.style.display = 'block';
            resultDiv.className = 'command-result';
            resultDiv.textContent = 'Setting production...';

            try {
                const response = await fetch(`${MCP_BASE}/tool`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        tool: 'set_city_production',
                        arguments: { city_id: cityId, order_type: orderType, item_id: itemId }
                    })
                });
                const data = await response.json();
                const result = data.result || data;
                const isError = data.status === 'error' || result.error;
                resultDiv.className = isError ? 'command-result error' : 'command-result success';
                resultDiv.textContent = JSON.stringify(result, null, 2);
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
            }
        }

        // Research management
        let loadedTechs = [];

        async function loadTechs() {
            const resultDiv = document.getElementById('commandResult');
            resultDiv.style.display = 'block';
            resultDiv.className = 'command-result';
            resultDiv.textContent = 'Loading available techs...';

            try {
                const response = await fetch(`${MCP_BASE}/tool`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tool: 'get_game_state', arguments: {}})
                });
                const data = await response.json();
                const result = data.result || data;

                if (data.status === 'error' || result.error) {
                    resultDiv.className = 'command-result error';
                    resultDiv.textContent = `Error: ${result.error || JSON.stringify(result)}`;
                    scheduleAutoHide();
                    return;
                }

                // Extract available techs from game state
                loadedTechs = result.available_techs || result.researchable_techs || [];

                const techSelect = document.getElementById('techSelect');
                const chooseTechBtn = document.getElementById('chooseTechBtn');

                techSelect.innerHTML = '<option value="">-- Select a tech --</option>';

                if (loadedTechs.length === 0) {
                    techSelect.innerHTML = '<option value="">-- No techs available --</option>';
                    techSelect.disabled = true;
                    chooseTechBtn.disabled = true;
                    resultDiv.className = 'command-result';
                    resultDiv.textContent = 'No researchable techs found in game state';
                    scheduleAutoHide();
                    return;
                }

                loadedTechs.forEach(tech => {
                    const opt = document.createElement('option');
                    opt.value = tech.id;
                    const turns = tech.turns ? ` (${tech.turns} turns)` : '';
                    const cost = tech.cost ? ` [${tech.cost}]` : '';
                    opt.textContent = `${tech.name}${turns}${cost}`;
                    techSelect.appendChild(opt);
                });

                techSelect.disabled = false;
                techSelect.onchange = () => {
                    chooseTechBtn.disabled = !techSelect.value;
                };

                resultDiv.className = 'command-result success';
                resultDiv.textContent = `Loaded ${loadedTechs.length} available techs`;
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
            }
        }

        async function chooseTech() {
            const techSelect = document.getElementById('techSelect');
            const resultDiv = document.getElementById('commandResult');

            const techId = parseInt(techSelect.value);

            if (isNaN(techId)) {
                resultDiv.style.display = 'block';
                resultDiv.className = 'command-result error';
                resultDiv.textContent = 'Please select a technology';
                scheduleAutoHide();
                return;
            }

            resultDiv.style.display = 'block';
            resultDiv.className = 'command-result';
            resultDiv.textContent = 'Setting research...';

            try {
                const response = await fetch(`${MCP_BASE}/tool`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        tool: 'choose_tech',
                        arguments: { tech_id: techId }
                    })
                });
                const data = await response.json();
                const result = data.result || data;
                const isError = data.status === 'error' || result.error;
                resultDiv.className = isError ? 'command-result error' : 'command-result success';
                resultDiv.textContent = JSON.stringify(result, null, 2);
                scheduleAutoHide();
            } catch (e) {
                resultDiv.className = 'command-result error';
                resultDiv.textContent = `Error: ${e.message}`;
                scheduleAutoHide();
            }
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            refreshMessages();
            checkHealth();
            setupAutoRefresh();

            // Message filter handlers
            document.getElementById('messageTypeFilter').addEventListener('change', refreshMessages);
            document.getElementById('directionFilter').addEventListener('change', refreshMessages);
            document.getElementById('messageTurnFilter').addEventListener('keyup', (e) => {
                if (e.key === 'Enter') refreshMessages();
            });
        });
    </script>
</body>
</html>
"""


def create_dashboard_app(mcp_server: Optional[CivMCPServer] = None) -> Flask:
    """Create and configure the Flask dashboard application.

    Args:
        mcp_server: CivMCPServer instance (single source of truth for all state)
    """
    app = Flask(__name__)
    app.config["mcp_server"] = mcp_server

    @app.route("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/state")
    def api_state():
        mcp = app.config.get("mcp_server")
        if mcp:
            # Query game state via the tool - this goes to the DLL
            try:
                result = mcp.execute_tool("get_game_state", {})
                return jsonify(result)
            except Exception as e:
                return jsonify({"error": f"Failed to get state: {e}"})
        return jsonify({"error": "No MCP server available"})

    @app.route("/api/tools")
    def api_tools():
        mcp = app.config.get("mcp_server")
        tools = mcp.get_tools() if mcp else []
        return jsonify({"tools": tools})

    @app.route("/api/session")
    def api_session():
        """Get current game and session info."""
        mcp = app.config.get("mcp_server")

        if mcp:
            return jsonify({
                "game_id": mcp.current_game_id,
                "session_id": mcp.current_session_id,
                "turn_number": mcp.turn_number,
                "connected": True
            })

        return jsonify({
            "game_id": None,
            "session_id": None,
            "turn_number": None,
            "connected": False
        })

    @app.route("/api/messages")
    def api_messages():
        """Get messages from JSONL log with optional filters."""
        from .game_logger import get_game_logger

        message_type = request.args.get("type")
        direction = request.args.get("direction")
        turn_number = request.args.get("turn_number", type=int)
        player_id = request.args.get("player_id", type=int)
        game_id = request.args.get("game_id", type=int)
        session_id = request.args.get("session_id", type=int)
        current_game_only = request.args.get("current_game", type=bool, default=False)
        limit = int(request.args.get("limit", 100))

        # Cap limit at 1000
        limit = min(limit, 1000)

        # If current_game_only and no explicit game_id, use current game from mcp_server
        mcp = app.config.get("mcp_server")
        if current_game_only and game_id is None and mcp:
            game_id = mcp.current_game_id

        # Get messages from singleton logger
        game_logger = get_game_logger()
        messages = game_logger.get_messages(
            message_type=message_type,
            player_id=player_id,
            game_id=game_id,
            session_id=session_id,
            turn_number=turn_number
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
                "turn_number": turn_number,
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
    debug: bool = False,
):
    """Run the Flask dashboard server.

    Args:
        host: Host to bind to
        port: Port to bind to
        mcp_server: CivMCPServer instance
        debug: Enable debug mode
    """
    app = create_dashboard_app(mcp_server)

    print(f"Dashboard running at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    import sys

    from .logging_setup import setup_logging

    setup_logging()

    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    run_dashboard(host, port, debug=True)
