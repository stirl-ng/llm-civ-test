"""
Flask Dashboard for Civilization V LLM Orchestrator

Provides a web interface for:
- Monitoring system status (DLL pipe, MCP server, game connection)
- Viewing detailed game state
- Tracking LLM activity (tool calls and messages)
- Viewing summary log
"""

import json
import time
from datetime import datetime
from typing import Optional

from flask import Flask, jsonify, render_template_string, request

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game_state import GameState

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
            flex-wrap: wrap;
            gap: 1rem;
        }
        .header h1 {
            color: #e94560;
            font-size: 1.5rem;
        }
        .status-bar {
            display: flex;
            gap: 1.5rem;
            align-items: center;
            flex-wrap: wrap;
        }
        .status-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.9rem;
        }
        .status-indicator {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #4ade80;
        }
        .status-indicator.disconnected {
            background: #ef4444;
        }
        .status-indicator.offline {
            background: #6b7280;
        }
        .status-label {
            color: #aaa;
            margin-right: 0.25rem;
        }
        .status-value {
            color: #eee;
            font-weight: 500;
        }
        .container {
            display: grid;
            grid-template-columns: 1fr 400px;
            gap: 1rem;
            padding: 1rem;
            min-height: calc(100vh - 120px);
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
            cursor: pointer;
        }
        .panel-header:hover {
            background: #1a4b8c;
        }
        .panel-body {
            flex: 1;
            overflow-y: auto;
            padding: 1rem;
        }
        .section {
            margin-bottom: 1.5rem;
        }
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem 0;
            border-bottom: 1px solid #0f3460;
            margin-bottom: 0.75rem;
            cursor: pointer;
        }
        .section-header:hover {
            color: #e94560;
        }
        .section-title {
            color: #e94560;
            font-size: 0.95rem;
            font-weight: 600;
        }
        .section-toggle {
            color: #888;
            font-size: 0.8rem;
        }
        .section-content {
            display: block;
        }
        .section-content.collapsed {
            display: none;
        }
        .card {
            background: #1a1a2e;
            border-radius: 4px;
            padding: 0.75rem;
            margin-bottom: 0.5rem;
        }
        .card-title {
            color: #4ade80;
            font-weight: 600;
            margin-bottom: 0.25rem;
        }
        .card-detail {
            color: #aaa;
            font-size: 0.85rem;
            margin-top: 0.25rem;
        }
        .stat-row {
            display: flex;
            justify-content: space-between;
            padding: 0.4rem 0;
            border-bottom: 1px solid #0f3460;
        }
        .stat-row:last-child {
            border-bottom: none;
        }
        .stat-label {
            color: #888;
        }
        .stat-value {
            color: #eee;
            font-weight: 500;
        }
        .table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }
        .table th {
            background: #0f3460;
            padding: 0.5rem;
            text-align: left;
            color: #e94560;
            font-weight: 600;
        }
        .table td {
            padding: 0.5rem;
            border-bottom: 1px solid #0f3460;
        }
        .table tr:hover {
            background: #1a1a2e;
        }
        .tool-call {
            padding: 0.5rem;
            margin-bottom: 0.5rem;
            background: #1a1a2e;
            border-radius: 4px;
            border-left: 3px solid #3b82f6;
            font-size: 0.85rem;
        }
        .tool-call.error {
            border-left-color: #ef4444;
        }
        .tool-call.success {
            border-left-color: #4ade80;
        }
        .tool-call-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.25rem;
        }
        .tool-name {
            color: #4ade80;
            font-weight: 600;
        }
        .tool-timestamp {
            color: #888;
            font-size: 0.75rem;
        }
        .tool-args {
            color: #aaa;
            font-size: 0.8rem;
            margin-top: 0.25rem;
        }
        .message-log {
            max-height: 500px;
            overflow-y: auto;
        }
        .message-entry {
            padding: 0.5rem 0.75rem;
            margin-bottom: 0.4rem;
            background: #1a1a2e;
            border-radius: 4px;
            font-size: 0.85rem;
            border-left: 3px solid #3b82f6;
            transition: background 0.2s;
        }
        .message-entry:hover {
            background: #1f1f3a;
        }
        .message-entry.request {
            border-left-color: #3b82f6;
        }
        .message-entry.response {
            border-left-color: #4ade80;
        }
        .message-entry .timestamp {
            color: #888;
            font-size: 0.75rem;
            margin-right: 0.75rem;
            font-family: 'Consolas', 'Monaco', monospace;
        }
        .message-entry .type-badge {
            display: inline-block;
            padding: 0.15rem 0.5rem;
            border-radius: 3px;
            font-size: 0.7rem;
            margin-right: 0.5rem;
            font-weight: 600;
        }
        .message-entry .type-badge.request {
            background: #3b82f6;
            color: #fff;
        }
        .message-entry .type-badge.response {
            background: #4ade80;
            color: #000;
        }
        .message-entry .summary {
            color: #eee;
            margin-left: 0.5rem;
        }
        .message-entry .model {
            color: #aaa;
            font-size: 0.75rem;
            margin-left: 0.5rem;
        }
        .message-entry .tool-call {
            color: #4ade80;
            font-weight: 600;
            margin-left: 0.5rem;
        }
        .pagination {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem;
            background: #0f3460;
            border-top: 1px solid #1a4b8c;
        }
        .pagination-info {
            color: #aaa;
            font-size: 0.85rem;
        }
        .pagination-controls {
            display: flex;
            gap: 0.5rem;
        }
        .pagination-btn {
            padding: 0.4rem 0.8rem;
            background: #1a1a2e;
            border: 1px solid #0f3460;
            border-radius: 4px;
            color: #eee;
            cursor: pointer;
            font-size: 0.8rem;
            transition: background 0.2s;
        }
        .pagination-btn:hover:not(:disabled) {
            background: #1f1f3a;
        }
        .pagination-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .summary-log {
            background: #16213e;
            border-radius: 8px;
            padding: 1rem;
            margin: 1rem;
            max-height: 200px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.85rem;
        }
        .summary-log-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.75rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid #0f3460;
        }
        .summary-log-header h3 {
            color: #e94560;
            font-size: 0.95rem;
        }
        .summary-entry {
            padding: 0.3rem 0;
            color: #aaa;
            border-bottom: 1px solid #0f3460;
        }
        .summary-entry:last-child {
            border-bottom: none;
        }
        .empty-state {
            color: #666;
            text-align: center;
            padding: 2rem;
        }
        .progress-bar {
            background: #0f3460;
            border-radius: 4px;
            height: 8px;
            overflow: hidden;
            margin-top: 0.25rem;
        }
        .progress-fill {
            background: #4ade80;
            height: 100%;
            transition: width 0.3s;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Civ V LLM Dashboard</h1>
        <div class="status-bar" id="statusBar">
            <div class="status-item">
                <div class="status-indicator" id="dllStatus"></div>
                <span class="status-label">DLL:</span>
                <span class="status-value" id="dllStatusText">Checking...</span>
            </div>
            <div class="status-item">
                <div class="status-indicator" id="mcpStatus"></div>
                <span class="status-label">MCP:</span>
                <span class="status-value" id="mcpStatusText">Checking...</span>
            </div>
            <div class="status-item">
                <div class="status-indicator" id="gameStatus"></div>
                <span class="status-label">Game:</span>
                <span class="status-value" id="gameStatusText">Checking...</span>
            </div>
            <div class="status-item">
                <span class="status-label">Turn:</span>
                <span class="status-value" id="turnNumber">-</span>
            </div>
        </div>
    </div>

    <div class="container">
        <div class="panel">
            <div class="panel-header">
                <span>Game State</span>
            </div>
            <div class="panel-body" id="gameStatePanel">
                <div class="empty-state">Loading game state...</div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-header">
                <span>LLM Activity</span>
            </div>
            <div class="panel-body" id="llmActivityPanel">
                <div class="section">
                    <div class="section-header" onclick="toggleSection('messageLogSection')">
                        <span class="section-title">LLM Messages</span>
                        <span class="section-toggle" id="messageLogToggle">▼</span>
                    </div>
                    <div class="section-content" id="messageLogSection">
                        <div class="message-log" id="messageLogList">
                            <div class="empty-state">No messages yet</div>
                        </div>
                        <div class="pagination" id="paginationControls" style="display: none;">
                            <div class="pagination-info" id="paginationInfo">Showing 0-0 of 0</div>
                            <div class="pagination-controls">
                                <button class="pagination-btn" id="prevBtn" onclick="loadPreviousPage()">Previous</button>
                                <button class="pagination-btn" id="nextBtn" onclick="loadNextPage()">Next</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="summary-log">
        <div class="summary-log-header">
            <h3>Summary Log</h3>
        </div>
        <div id="summaryLogContent">
            <div class="summary-entry">Waiting for activity...</div>
        </div>
    </div>

    <script>
        const MCP_BASE = 'http://localhost:8765';
        const DASHBOARD_BASE = '';
        let refreshIntervals = {};

        function toggleSection(sectionId) {
            const section = document.getElementById(sectionId);
            const toggle = document.getElementById(sectionId.replace('Section', 'Toggle'));
            section.classList.toggle('collapsed');
            toggle.textContent = section.classList.contains('collapsed') ? '▶' : '▼';
        }

        function formatTimestamp(timestamp) {
            if (!timestamp) return 'N/A';
            const date = new Date(timestamp);
            return date.toLocaleTimeString();
        }

        function formatTimeAgo(timestamp) {
            if (!timestamp) return 'N/A';
            const date = new Date(timestamp);
            const now = new Date();
            const diff = Math.floor((now - date) / 1000);
            if (diff < 60) return `${diff}s ago`;
            if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
            return `${Math.floor(diff / 3600)}h ago`;
        }

        // System Status
        async function refreshSystemStatus() {
            try {
                const response = await fetch(`${DASHBOARD_BASE}/api/system_status`);
                const data = await response.json();
                
                // DLL Status
                const dllIndicator = document.getElementById('dllStatus');
                const dllText = document.getElementById('dllStatusText');
                if (data.dll_connected) {
                    dllIndicator.classList.remove('disconnected', 'offline');
                    dllText.textContent = 'Connected';
                } else {
                    dllIndicator.classList.add('disconnected');
                    dllIndicator.classList.remove('offline');
                    dllText.textContent = 'Disconnected';
                }

                // MCP Status
                const mcpIndicator = document.getElementById('mcpStatus');
                const mcpText = document.getElementById('mcpStatusText');
                if (data.mcp_online) {
                    mcpIndicator.classList.remove('disconnected', 'offline');
                    mcpText.textContent = 'Online';
                } else {
                    mcpIndicator.classList.add('offline');
                    mcpIndicator.classList.remove('disconnected');
                    mcpText.textContent = 'Offline';
                }

                // Game Status
                const gameIndicator = document.getElementById('gameStatus');
                const gameText = document.getElementById('gameStatusText');
                if (data.game_active) {
                    gameIndicator.classList.remove('disconnected', 'offline');
                    gameText.textContent = 'Active';
                } else {
                    gameIndicator.classList.add('offline');
                    gameIndicator.classList.remove('disconnected');
                    gameText.textContent = 'Inactive';
                }

                // Turn Number
                const turnNumber = document.getElementById('turnNumber');
                turnNumber.textContent = data.turn_number !== null ? data.turn_number : '-';
            } catch (e) {
                console.error('Failed to fetch system status:', e);
            }
        }

        // Game State
        async function refreshGameState() {
            try {
                const response = await fetch(`${DASHBOARD_BASE}/api/game_state_summary`);
                const data = await response.json();
                const panel = document.getElementById('gameStatePanel');

                if (data.error) {
                    panel.innerHTML = `<div class="empty-state">${data.error}</div>`;
                    return;
                }

                let html = '';

                // Session Info
                html += '<div class="section">';
                html += '<div class="section-header" onclick="toggleSection(\'sessionSection\')">';
                html += '<span class="section-title">Session Info</span>';
                html += '<span class="section-toggle" id="sessionToggle">▼</span>';
                html += '</div>';
                html += '<div class="section-content" id="sessionSection">';
                html += '<div class="card">';
                html += `<div class="stat-row"><span class="stat-label">Turn:</span><span class="stat-value">${data.turn_number !== null ? data.turn_number : 'N/A'}</span></div>`;
                html += `<div class="stat-row"><span class="stat-label">Player:</span><span class="stat-value">${data.player_name || 'N/A'}</span></div>`;
                html += `<div class="stat-row"><span class="stat-label">Game ID:</span><span class="stat-value">${data.game_id !== null ? data.game_id : 'N/A'}</span></div>`;
                html += `<div class="stat-row"><span class="stat-label">Session ID:</span><span class="stat-value">${data.session_id !== null ? data.session_id : 'N/A'}</span></div>`;
                html += '</div>';
                html += '</div>';
                html += '</div>';

                // Cities
                if (data.cities && data.cities.length > 0) {
                    html += '<div class="section">';
                    html += '<div class="section-header" onclick="toggleSection(\'citiesSection\')">';
                    html += `<span class="section-title">Cities (${data.cities.length})</span>`;
                    html += '<span class="section-toggle" id="citiesToggle">▼</span>';
                    html += '</div>';
                    html += '<div class="section-content" id="citiesSection">';
                    data.cities.forEach(city => {
                        html += '<div class="card">';
                        html += `<div class="card-title">${city.name || 'Unknown'}</div>`;
                        html += `<div class="card-detail">Pop: ${city.population || 'N/A'} | Production: ${city.current_production || city.producing || 'None'}</div>`;
                        if (city.food_per_turn !== undefined) {
                            html += `<div class="card-detail">Food: ${city.food_per_turn}/turn | Production: ${city.production_per_turn || 0}/turn</div>`;
                        }
                        html += '</div>';
                    });
                    html += '</div>';
                    html += '</div>';
                }

                // Units
                if (data.units && data.units.length > 0) {
                    html += '<div class="section">';
                    html += '<div class="section-header" onclick="toggleSection(\'unitsSection\')">';
                    html += `<span class="section-title">Units (${data.units.length})</span>`;
                    html += '<span class="section-toggle" id="unitsToggle">▼</span>';
                    html += '</div>';
                    html += '<div class="section-content" id="unitsSection">';
                    html += '<table class="table">';
                    html += '<thead><tr><th>Type</th><th>Position</th><th>Moves</th><th>HP</th></tr></thead>';
                    html += '<tbody>';
                    data.units.forEach(unit => {
                        const name = unit.unit_type_name || unit.name || unit.type || 'Unknown';
                        const moves = unit.moves_remaining ?? unit.moves ?? 'N/A';
                        const hp = unit.max_hit_points != null ? (unit.max_hit_points - (unit.damage || 0)) : (unit.hp ?? 'N/A');
                        const maxHp = unit.max_hit_points ?? unit.max_hp ?? 'N/A';
                        html += `<tr>`;
                        html += `<td>${name}</td>`;
                        html += `<td>(${unit.x}, ${unit.y})</td>`;
                        html += `<td>${moves}</td>`;
                        html += `<td>${hp}/${maxHp}</td>`;
                        html += `</tr>`;
                    });
                    html += '</tbody></table>';
                    html += '</div>';
                    html += '</div>';
                }

                // Technology
                if (data.current_tech || (data.available_techs && data.available_techs.length > 0)) {
                    html += '<div class="section">';
                    html += '<div class="section-header" onclick="toggleSection(\'techSection\')">';
                    html += '<span class="section-title">Technology</span>';
                    html += '<span class="section-toggle" id="techToggle">▼</span>';
                    html += '</div>';
                    html += '<div class="section-content" id="techSection">';
                    if (data.current_tech) {
                        html += '<div class="card">';
                        html += `<div class="card-title">Researching: ${data.current_tech.name || 'Unknown'}</div>`;
                        if (data.current_tech.turns !== undefined) {
                            html += `<div class="card-detail">Turns remaining: ${data.current_tech.turns}</div>`;
                        }
                        html += '</div>';
                    }
                    if (data.available_techs && data.available_techs.length > 0) {
                        html += '<div class="card">';
                        html += `<div class="card-title">Available Techs (${data.available_techs.length})</div>`;
                        data.available_techs.slice(0, 5).forEach(tech => {
                            html += `<div class="card-detail">${tech.name || 'Unknown'}${tech.turns ? ` (${tech.turns} turns)` : ''}</div>`;
                        });
                        if (data.available_techs.length > 5) {
                            html += `<div class="card-detail">... and ${data.available_techs.length - 5} more</div>`;
                        }
                        html += '</div>';
                    }
                    html += '</div>';
                    html += '</div>';
                }

                // Resources
                if (data.resources && (data.resources.strategic || data.resources.luxury)) {
                    html += '<div class="section">';
                    html += '<div class="section-header" onclick="toggleSection(\'resourcesSection\')">';
                    html += '<span class="section-title">Resources</span>';
                    html += '<span class="section-toggle" id="resourcesToggle">▼</span>';
                    html += '</div>';
                    html += '<div class="section-content" id="resourcesSection">';
                    if (data.resources.strategic && data.resources.strategic.length > 0) {
                        html += '<div class="card">';
                        html += '<div class="card-title">Strategic Resources</div>';
                        data.resources.strategic.forEach(res => {
                            html += `<div class="card-detail">${res.name || 'Unknown'}: ${res.amount || 0}</div>`;
                        });
                        html += '</div>';
                    }
                    if (data.resources.luxury && data.resources.luxury.length > 0) {
                        html += '<div class="card">';
                        html += '<div class="card-title">Luxury Resources</div>';
                        data.resources.luxury.forEach(res => {
                            html += `<div class="card-detail">${res.name || 'Unknown'}: ${res.amount || 0}</div>`;
                        });
                        html += '</div>';
                    }
                    html += '</div>';
                    html += '</div>';
                }

                if (html === '') {
                    html = '<div class="empty-state">No game state available</div>';
                }

                panel.innerHTML = html;
            } catch (e) {
                console.error('Failed to fetch game state:', e);
                document.getElementById('gameStatePanel').innerHTML = '<div class="empty-state">Error loading game state</div>';
            }
        }

        // LLM Activity - pagination state
        let llmPaginationState = {
            offset: 0,
            limit: 50,
            total: 0
        };

        // Debounce helper
        function debounce(func, wait) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        }

        // LLM Activity
        async function refreshLLMActivity(resetOffset = false) {
            try {
                if (resetOffset) {
                    llmPaginationState.offset = 0;
                }
                
                const params = new URLSearchParams({
                    limit: llmPaginationState.limit.toString(),
                    offset: llmPaginationState.offset.toString()
                });
                
                const response = await fetch(`${DASHBOARD_BASE}/api/llm_activity?${params}`);
                const data = await response.json();

                // Update pagination state
                if (data.total !== undefined) {
                    llmPaginationState.total = data.total;
                }

                // Message Log
                const messageLogList = document.getElementById('messageLogList');
                const paginationControls = document.getElementById('paginationControls');
                
                if (data.messages && data.messages.length > 0) {
                    messageLogList.innerHTML = data.messages.map(msg => {
                        const timestamp = formatTimestamp(msg.timestamp);
                        const type = msg.type || 'unknown';
                        const typeClass = type === 'request' ? 'request' : 'response';
                        const typeBadge = type === 'request' ? 'REQ' : 'RES';
                        
                        let html = `
                            <div class="message-entry ${typeClass}">
                                <span class="timestamp">${timestamp}</span>
                                <span class="type-badge ${typeClass}">${typeBadge}</span>
                        `;
                        
                        if (msg.model) {
                            html += `<span class="model">${msg.model}</span>`;
                        }
                        
                        if (msg.tool_call) {
                            html += `<span class="tool-call">→ ${msg.tool_call}</span>`;
                        }
                        
                        html += `<span class="summary">${msg.summary || ''}</span>`;
                        html += `</div>`;
                        
                        return html;
                    }).join('');
                    
                    // Show pagination if there are more messages
                    if (llmPaginationState.total > llmPaginationState.limit) {
                        paginationControls.style.display = 'flex';
                        updatePaginationInfo();
                    } else {
                        paginationControls.style.display = 'none';
                    }
                    
                    // Auto-scroll to top for new messages (when offset is 0)
                    if (llmPaginationState.offset === 0) {
                        messageLogList.scrollTop = 0;
                    }
                } else {
                    messageLogList.innerHTML = '<div class="empty-state">No messages yet</div>';
                    paginationControls.style.display = 'none';
                }
            } catch (e) {
                console.error('Failed to fetch LLM activity:', e);
            }
        }

        function updatePaginationInfo() {
            const info = document.getElementById('paginationInfo');
            const start = llmPaginationState.offset + 1;
            const end = Math.min(llmPaginationState.offset + llmPaginationState.limit, llmPaginationState.total);
            info.textContent = `Showing ${start}-${end} of ${llmPaginationState.total}`;
            
            const prevBtn = document.getElementById('prevBtn');
            const nextBtn = document.getElementById('nextBtn');
            
            prevBtn.disabled = llmPaginationState.offset === 0;
            nextBtn.disabled = llmPaginationState.offset + llmPaginationState.limit >= llmPaginationState.total;
        }

        function loadNextPage() {
            if (llmPaginationState.offset + llmPaginationState.limit < llmPaginationState.total) {
                llmPaginationState.offset += llmPaginationState.limit;
                refreshLLMActivity(false);
            }
        }

        function loadPreviousPage() {
            if (llmPaginationState.offset > 0) {
                llmPaginationState.offset = Math.max(0, llmPaginationState.offset - llmPaginationState.limit);
                refreshLLMActivity(false);
            }
        }

        // Debounced refresh for high-volume updates
        const debouncedRefreshLLM = debounce(() => refreshLLMActivity(true), 1000);

        // Summary Log
        async function refreshSummaryLog() {
            try {
                const response = await fetch(`${DASHBOARD_BASE}/api/messages?limit=20&summary=true`);
                const data = await response.json();
                const content = document.getElementById('summaryLogContent');

                if (data.messages && data.messages.length > 0) {
                    content.innerHTML = data.messages.map(msg => {
                        const timestamp = formatTimestamp(msg.timestamp);
                        const summary = msg.summary || `${msg.type || 'message'}`;
                        return `<div class="summary-entry">[${timestamp}] ${summary}</div>`;
                    }).join('');
                    // Auto-scroll to bottom
                    const summaryLog = content.parentElement;
                    summaryLog.scrollTop = summaryLog.scrollHeight;
                } else {
                    content.innerHTML = '<div class="summary-entry">No activity yet</div>';
                }
            } catch (e) {
                console.error('Failed to fetch summary log:', e);
            }
        }

        // Setup auto-refresh
        function setupAutoRefresh() {
            // System status every 2 seconds
            refreshSystemStatus();
            refreshIntervals.systemStatus = setInterval(refreshSystemStatus, 2000);

            // Game state every 3 seconds
            refreshGameState();
            refreshIntervals.gameState = setInterval(refreshGameState, 3000);

            // LLM activity - use debounced refresh for high volume
            refreshLLMActivity(true);
            refreshIntervals.llmActivity = setInterval(() => debouncedRefreshLLM(), 2000);

            // Summary log every 2 seconds
            refreshSummaryLog();
            refreshIntervals.summaryLog = setInterval(refreshSummaryLog, 2000);
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            setupAutoRefresh();
        });
    </script>
</body>
</html>
"""


def create_dashboard_app(
    mcp_server: Optional[CivMCPServer] = None,
    game_state: Optional["GameState"] = None
) -> Flask:
    """Create and configure the Flask dashboard application.

    Args:
        mcp_server: CivMCPServer instance for tool execution
        game_state: GameState instance (single source of truth for metadata)
    """
    app = Flask(__name__)
    app.config["mcp_server"] = mcp_server
    app.config["game_state"] = game_state

    @app.route("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/system_status")
    def api_system_status():
        """Get system status (DLL pipe, MCP server, game connection)."""
        game_state_obj = app.config.get("game_state")
        mcp = app.config.get("mcp_server")

        # DLL connection status
        dll_connected = False
        if game_state_obj:
            dll_connected = game_state_obj.connected

        # MCP server status (check health endpoint)
        mcp_online = False
        if mcp:
            try:
                import urllib.request
                import urllib.error
                req = urllib.request.Request(f"http://localhost:8765/health", method="GET")
                with urllib.request.urlopen(req, timeout=1) as response:
                    if response.status == 200:
                        mcp_online = True
            except Exception:
                pass

        # Game active status
        game_active = False
        turn_number = None
        if game_state_obj:
            metadata = game_state_obj.get_metadata()
            game_active = metadata.get("turn_number") is not None and metadata.get("connected", False)
            turn_number = metadata.get("turn_number")

        return jsonify({
            "dll_connected": dll_connected,
            "mcp_online": mcp_online,
            "game_active": game_active,
            "turn_number": turn_number,
        })

    @app.route("/api/game_state_summary")
    def api_game_state_summary():
        """Get formatted game state summary."""
        mcp = app.config.get("mcp_server")
        game_state_obj = app.config.get("game_state")

        if not mcp:
            return jsonify({"error": "No MCP server available"})

        try:
            # Get game state from MCP server
            result = mcp.execute_tool("get_game_state", {})
            
            # Extract data from result
            state_data = result.get("result", result) if isinstance(result, dict) and "result" in result else result

            # Format response
            summary = {
                "turn_number": None,
                "player_name": None,
                "game_id": None,
                "session_id": None,
                "cities": [],
                "units": [],
                "current_tech": None,
                "available_techs": [],
                "resources": {
                    "strategic": [],
                    "luxury": []
                }
            }

            # Get metadata from game_state
            if game_state_obj:
                metadata = game_state_obj.get_metadata()
                summary["turn_number"] = metadata.get("turn_number")
                summary["player_name"] = metadata.get("player_name")
                summary["game_id"] = metadata.get("game_id")
                summary["session_id"] = metadata.get("session_id")

            # Extract cities
            if "cities" in state_data:
                summary["cities"] = state_data["cities"]
            elif "result" in state_data and "cities" in state_data["result"]:
                summary["cities"] = state_data["result"]["cities"]

            # Extract units
            if "units" in state_data:
                summary["units"] = state_data["units"]
            elif "result" in state_data and "units" in state_data["result"]:
                summary["units"] = state_data["result"]["units"]

            # Extract technology info
            if "current_tech" in state_data:
                summary["current_tech"] = state_data["current_tech"]
            elif "researching_tech" in state_data:
                summary["current_tech"] = state_data["researching_tech"]

            if "available_techs" in state_data:
                summary["available_techs"] = state_data["available_techs"]
            elif "researchable_techs" in state_data:
                summary["available_techs"] = state_data["researchable_techs"]

            # Extract resources (if available)
            if "resources" in state_data:
                summary["resources"] = state_data["resources"]
            elif "strategic_resources" in state_data or "luxury_resources" in state_data:
                summary["resources"] = {
                    "strategic": state_data.get("strategic_resources", []),
                    "luxury": state_data.get("luxury_resources", [])
                }

            return jsonify(summary)
        except Exception as e:
            return jsonify({"error": f"Failed to get game state: {e}"})

    @app.route("/api/llm_activity")
    def api_llm_activity():
        """Get recent LLM activity from llm_messages.jsonl."""
        from .llm_logger import get_llm_logger
        import json
        from pathlib import Path

        try:
            limit = int(request.args.get("limit", 100))
            offset = int(request.args.get("offset", 0))
            
            # Cap limit at 500 for performance
            limit = min(limit, 500)
            
            # Get LLM logger instance to find the log file path
            llm_logger = get_llm_logger()
            log_file = llm_logger.messages_file
            
            # If relative path, make it absolute based on module location
            if not log_file.is_absolute():
                module_dir = Path(__file__).parent.parent
                log_file = module_dir / log_file
            
            if not log_file.exists():
                return jsonify({
                    "messages": [],
                    "total": 0,
                    "count": 0
                })
            
            # Read file efficiently - read from end backwards
            with open(log_file, "r", encoding="utf-8") as f:
                # For efficiency with large files, read last N lines
                # This is a simple approach - for very large files, consider tail command
                all_lines = f.readlines()
                
            # Parse JSONL from end (most recent first)
            parsed_messages = []
            for line in reversed(all_lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    parsed_messages.append(msg)
                except json.JSONDecodeError:
                    continue
            
            # Apply pagination
            total = len(parsed_messages)
            paginated = parsed_messages[offset:offset + limit]
            
            # Format messages for display
            formatted_messages = []
            for msg in paginated:
                msg_type = msg.get("type", "unknown")
                timestamp = msg.get("timestamp", "")
                
                if msg_type == "llm_request":
                    model = msg.get("model", "unknown")
                    # Extract tool calls from messages if present
                    messages_list = msg.get("messages", [])
                    last_msg = messages_list[-1] if messages_list else {}
                    content = last_msg.get("content", "")
                    
                    # Try to extract tool call from content
                    tool_call = None
                    if "mcp_call" in content:
                        # Simple extraction - look for tool name
                        import re
                        match = re.search(r"tool=['\"]([^'\"]+)['\"]", content)
                        if match:
                            tool_call = match.group(1)
                    
                    formatted_messages.append({
                        "type": "request",
                        "timestamp": timestamp,
                        "model": model,
                        "tool_call": tool_call,
                        "uuid": msg.get("uuid"),
                        "summary": f"Request to {model}" + (f" → {tool_call}" if tool_call else "")
                    })
                elif msg_type == "llm_response":
                    response = msg.get("response", "")
                    # Extract tool call from response
                    tool_call = None
                    if "mcp_call" in response:
                        import re
                        match = re.search(r"tool=['\"]([^'\"]+)['\"]", response)
                        if match:
                            tool_call = match.group(1)
                    
                    formatted_messages.append({
                        "type": "response",
                        "timestamp": timestamp,
                        "tool_call": tool_call,
                        "request_uuid": msg.get("request_uuid"),
                        "summary": f"Response" + (f" → {tool_call}" if tool_call else ""),
                        "response_preview": response[:200] + "..." if len(response) > 200 else response
                    })
            
            return jsonify({
                "messages": formatted_messages,
                "total": total,
                "count": len(formatted_messages),
                "offset": offset,
                "limit": limit
            })
        except Exception as e:
            import logging
            logging.error(f"Error loading LLM activity: {e}", exc_info=True)
            return jsonify({
                "messages": [],
                "total": 0,
                "count": 0,
                "error": str(e)
            })

    @app.route("/api/messages")
    def api_messages():
        """Get messages from JSONL log with optional filters."""
        from .game_logger import get_game_logger

        try:
            message_type = request.args.get("type")
            direction = request.args.get("direction")
            turn_number = request.args.get("turn_number", type=int)
            player_id = request.args.get("player_id", type=int)
            game_id = request.args.get("game_id", type=int)
            session_id = request.args.get("session_id", type=int)
            current_game_only = request.args.get("current_game", type=bool, default=False)
            limit = int(request.args.get("limit", 100))
            summary_format = request.args.get("summary", type=bool, default=False)

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

            # Format as summary if requested
            if summary_format:
                formatted_messages = []
                for msg in messages:
                    msg_type = msg.get("type", "unknown")
                    direction = msg.get("direction", "unknown")
                    
                    if msg_type == "turn_start":
                        turn = msg.get("turn", "?")
                        summary = f"Turn {turn} started"
                    elif msg_type == "turn_complete":
                        turn = msg.get("turn", "?")
                        summary = f"Turn {turn} completed"
                    elif msg_type == "notification":
                        notif_type = msg.get("notification_type", "notification")
                        summary = f"Notification: {notif_type}"
                    elif msg_type == "action_result":
                        action_kind = msg.get("kind", "action")
                        success = msg.get("success", False)
                        summary = f"Action: {action_kind} ({'success' if success else 'failed'})"
                    elif msg_type == "tool_request":
                        tool = msg.get("tool", "unknown")
                        summary = f"LLM called: {tool}"
                    elif msg_type == "tool_response":
                        tool = msg.get("tool", "unknown")
                        result = msg.get("result", {})
                        if result.get("error") or result.get("status") == "error":
                            summary = f"Tool response: {tool} (error)"
                        else:
                            summary = f"Tool response: {tool} (success)"
                    else:
                        summary = f"{msg_type} ({direction})"

                    formatted_messages.append({
                        "timestamp": msg.get("timestamp"),
                        "type": msg_type,
                        "summary": summary
                    })
                messages = formatted_messages

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
        except Exception as e:
            import logging
            logging.error(f"Error loading messages: {e}", exc_info=True)
            return jsonify({
                "messages": [],
                "count": 0,
                "error": str(e)
            })

    @app.route("/api/session")
    def api_session():
        """Get current game and session info."""
        game_state_obj = app.config.get("game_state")
        
        if game_state_obj:
            metadata = game_state_obj.get_metadata()
            return jsonify({
                "game_id": metadata["game_id"],
                "session_id": metadata["session_id"],
                "turn_number": metadata["turn_number"],
                "player_id": metadata["player_id"],
                "player_name": metadata["player_name"],
                "connected": metadata["connected"]
            })

        return jsonify({
            "game_id": None,
            "session_id": None,
            "turn_number": None,
            "player_id": None,
            "player_name": None,
            "connected": False
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
