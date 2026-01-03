"""
HTTP-based MCP Server for Civilization V

Provides an HTTP interface for LLMs to control the game via tool calls.
Runs in a background thread alongside the main orchestrator loop.
"""

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Optional, TYPE_CHECKING

from .mcp_server import AVAILABLE_TOOLS, CivMCPServer

if TYPE_CHECKING:
    from .turn_manager import TurnManager

logger = logging.getLogger(__name__)


class MCPHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MCP server."""

    mcp_server: CivMCPServer = None  # Set by MCPHTTPServer

    def log_message(self, format: str, *args):
        """Override to use our logger."""
        logger.debug(format % args)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            self._send_json({"status": "ok", "server": "civ5-mcp"})

        elif self.path == "/state":
            state = self.mcp_server.current_state or {}
            turn_active = self.mcp_server.turn_manager.turn_active
            turn_num = self.mcp_server.turn_manager.turn_number
            self._send_json({
                "turn_active": turn_active,
                "turn": turn_num,
                "state": state
            })

        elif self.path == "/tools":
            self._send_json({"tools": AVAILABLE_TOOLS})

        elif self.path == "/turn":
            tm = self.mcp_server.turn_manager
            self._send_json({
                "turn_active": tm.turn_active,
                "turn": tm.turn_number,
                "player_id": tm._player_id
            })

        else:
            self._send_error(404, "Not found")

    def do_POST(self):
        """Handle POST requests for tool calls."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON")
            return

        if self.path == "/tool":
            self._handle_tool_call(request)
        else:
            self._send_error(404, "Not found")

    def _handle_tool_call(self, request: dict):
        """Handle a tool call request."""
        tool_name = request.get("tool")
        arguments = request.get("arguments", {})

        if not tool_name:
            self._send_error(400, "Missing 'tool' field")
            return

        try:
            result = self.mcp_server.execute_tool(tool_name, arguments)
            self._send_json({"status": "success", "result": result})
        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            self._send_json({"status": "error", "error": str(e)}, status=500)

    def _send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _send_error(self, status: int, message: str):
        """Send error response."""
        self._send_json({"error": message}, status=status)


class MCPHTTPServer:
    """HTTP server wrapper for MCP server."""

    def __init__(self, turn_manager: "TurnManager", host: str = "localhost", port: int = 8765):
        """Initialize HTTP server.

        Args:
            turn_manager: TurnManager for DLL communication
            host: Host to bind to
            port: Port to listen on
        """
        self.host = host
        self.port = port
        self.turn_manager = turn_manager
        self.mcp_server = CivMCPServer(turn_manager)
        self.http_server: Optional[HTTPServer] = None
        self.thread: Optional[Thread] = None

    def start(self):
        """Start the HTTP server in a background thread."""
        MCPHTTPHandler.mcp_server = self.mcp_server

        self.http_server = HTTPServer((self.host, self.port), MCPHTTPHandler)
        self.thread = Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()

        logger.info(f"MCP HTTP Server started on http://{self.host}:{self.port}")

    def stop(self):
        """Stop the HTTP server."""
        if self.http_server:
            self.http_server.shutdown()
            logger.info("MCP HTTP Server stopped")
