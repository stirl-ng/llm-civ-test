"""
HTTP-based MCP Server for Civilization V

This provides an HTTP interface for the MCP server, allowing it to run
alongside the orchestrator without conflicting with stdio transport.
"""

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from threading import Thread

from .mcp_server import CivMCPServer

logger = logging.getLogger(__name__)


class MCPHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MCP server."""

    mcp_server: CivMCPServer = None  # Set by server instance

    def log_message(self, format: str, *args):
        """Override to use our logger."""
        logger.info(format % args)

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            self._send_json({"status": "ok", "server": "civ5-mcp"})
        elif self.path == "/state":
            state = self.mcp_server.current_state or {}
            self._send_json(state)
        elif self.path == "/tools":
            # List available tools (would integrate with MCP protocol)
            self._send_json({
                "tools": [
                    "get_game_state", "send_action", "send_actions",
                    "get_cities", "get_units", "get_tech_tree",
                    "get_diplomacy", "get_available_choices",
                    "get_victory_progress", "get_resources", "format_state"
                ]
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
        elif self.path == "/state":
            # Update state (called by orchestrator)
            self.mcp_server.update_state(request)
            self._send_json({"status": "updated"})
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
            # Execute tool using the MCP server's logic
            result = asyncio.run(self.mcp_server._execute_tool(tool_name, arguments))
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

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.mcp_server = CivMCPServer()
        self.http_server: Optional[HTTPServer] = None
        self.thread: Optional[Thread] = None

    def start(self):
        """Start the HTTP server in a background thread."""
        # Set the MCP server instance on the handler class
        MCPHTTPHandler.mcp_server = self.mcp_server

        # Create HTTP server
        self.http_server = HTTPServer((self.host, self.port), MCPHTTPHandler)

        # Start in background thread
        self.thread = Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()

        logger.info(f"MCP HTTP Server started on http://{self.host}:{self.port}")
        logger.info(f"Health check: http://{self.host}:{self.port}/health")
        logger.info(f"State endpoint: http://{self.host}:{self.port}/state")
        logger.info(f"Tool endpoint: http://{self.host}:{self.port}/tool")

    def stop(self):
        """Stop the HTTP server."""
        if self.http_server:
            self.http_server.shutdown()
            logger.info("MCP HTTP Server stopped")

    def update_state(self, state: dict):
        """Update the game state (called by orchestrator)."""
        self.mcp_server.update_state(state)

    def get_pending_actions(self) -> list:
        """Get pending actions (called by orchestrator)."""
        return self.mcp_server.get_pending_actions()


def run_http_server(host: str = "localhost", port: int = 8765):
    """Run the MCP HTTP server standalone."""
    server = MCPHTTPServer(host, port)
    server.start()

    print(f"MCP HTTP Server running on http://{host}:{port}")
    print("Press Ctrl+C to stop...")

    try:
        # Keep main thread alive
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765

    run_http_server(host, port)
