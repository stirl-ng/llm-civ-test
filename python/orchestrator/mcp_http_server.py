"""
HTTP-based MCP Server for Civilization V

Provides an HTTP interface for LLMs to control the game via tool calls.
Runs alongside the orchestrator in a background thread.

Sequential action flow:
- LLM calls send_action via POST /tool
- Action is sent immediately to DLL, response returned to LLM
- LLM can react to results before sending next action
"""

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Optional

from .mcp_server import CivMCPServer

logger = logging.getLogger(__name__)


class MCPHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MCP server."""

    mcp_server: CivMCPServer = None  # Set by MCPHTTPServer

    def log_message(self, format: str, *args):
        """Override to use our logger."""
        # Suppress logging for health check endpoints to reduce spam
        message = format % args
        if "/status" in message or "/health" in message:
            logger.debug(message)
        else:
            logger.info(message)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def _send_cors_headers(self):
        """Add CORS headers to response."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            self._send_json({"status": "ok", "server": "civ5-mcp"})

        elif self.path == "/status":
            # Return game status for experiments.run module
            # print(self.mcp_server.game_state.get_metadata())
            if self.mcp_server and self.mcp_server.game_state:
                metadata = self.mcp_server.game_state.get_metadata()
                self._send_json({
                    "connected": metadata.get("connected", False),
                    "turn": metadata.get("turn_number"),
                    "game_id": metadata.get("game_id"),
                    "session_id": metadata.get("session_id"),
                    "player_id": metadata.get("player_id"),
                    "player_name": metadata.get("player_name"),
                    "blockers": metadata.get("blockers", []),
                })
            else:
                self._send_json({
                    "connected": False,
                    "turn": None,
                    "game_id": None,
                    "session_id": None,
                    "player_id": None,
                    "player_name": None,
                    "blockers": [],
                })

        elif self.path == "/about":
            about = self.mcp_server.get_about()
            self._send_json({"about": about})

        elif self.path == "/tools":
            tools = self.mcp_server.get_tools()
            self._send_json({"tools": tools})

        else:
            self._send_error(404, "Not found")

    def do_POST(self):
        """Handle POST requests for tool calls."""
        content_length_str = self.headers.get("Content-Length")
        if not content_length_str:
            self._send_error(400, "Missing Content-Length header")
            return
        
        try:
            content_length = int(content_length_str)
        except ValueError:
            self._send_error(400, f"Invalid Content-Length: {content_length_str}")
            return
        
        if content_length < 0:
            self._send_error(400, f"Content-Length must be non-negative, got {content_length}")
            return
        
        # Limit max body size to prevent DoS (10MB)
        MAX_BODY_SIZE = 10 * 1024 * 1024
        if content_length > MAX_BODY_SIZE:
            self._send_error(413, f"Request body too large: {content_length} bytes (max {MAX_BODY_SIZE})")
            return
        
        body = self.rfile.read(content_length)
        
        if len(body) != content_length:
            self._send_error(400, f"Incomplete request body: expected {content_length} bytes, got {len(body)}")
            return

        try:
            request = json.loads(body)
        except json.JSONDecodeError as e:
            self._send_error(400, f"Invalid JSON: {e}")
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

        # Log tool request (outgoing from LLM to orchestrator)
        from .message_logger import get_message_logger
        get_message_logger().log({
            "type": "tool_request",
            "tool": tool_name,
            "arguments": arguments,
        }, direction="outgoing")

        try:
            result = self.mcp_server.execute_tool(tool_name, arguments)
            # Check if result indicates an error (DLL uses "type": "error", others use "status": "error")
            is_error = (
                result.get("status") == "error"
                or result.get("type") == "error"
                or "error" in result
            )
            # Return result directly with 'ok' flag - no nested 'result' wrapper
            result["ok"] = not is_error
            self._send_json(result)
        except Exception as e:
            import traceback
            logger.error(f"Exception executing tool '{tool_name}': {e} arguments: {arguments} traceback: {traceback.format_exc()}")
            self._send_json({"ok": False, "error": str(e)}, status=500)

    def _send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _send_error(self, status: int, message: str):
        """Send error response."""
        self._send_json({"error": message}, status=status)


class MCPHTTPServer:
    """HTTP server that exposes CivMCPServer tools via HTTP.

    This is just a thin HTTP layer - the actual logic lives in CivMCPServer.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        mcp_server: Optional[CivMCPServer] = None
    ):
        self.host = host
        self.port = port
        self.mcp_server = mcp_server
        self.http_server: Optional[HTTPServer] = None
        self.thread: Optional[Thread] = None

    def start(self):
        """Start the HTTP server in a background thread."""
        if self.mcp_server is None:
            raise RuntimeError("MCPHTTPServer requires an mcp_server instance")

        MCPHTTPHandler.mcp_server = self.mcp_server

        self.http_server = HTTPServer((self.host, self.port), MCPHTTPHandler)
        self.thread = Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()

        logger.info(f"MCP HTTP Server started on http://{self.host}:{self.port}")
        logger.info(f"Endpoints: GET /health, GET /tools, POST /tool")

    def stop(self):
        """Stop the HTTP server."""
        if self.http_server:
            self.http_server.shutdown()
            logger.info("MCP HTTP Server stopped")
