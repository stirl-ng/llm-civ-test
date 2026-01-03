"""
HTTP-based MCP Server for Civilization V

Provides an HTTP interface for LLMs to control the game via tool calls.
Runs alongside the orchestrator in a background thread.
"""

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Optional

from .mcp_server import AVAILABLE_TOOLS, CivMCPServer

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
            self._send_json({"tools": AVAILABLE_TOOLS})
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
    """HTTP server wrapper for MCP server.

    Turn-based flow:
    1. Orchestrator calls start_turn(state) when DLL signals turn
    2. LLM makes HTTP calls to /tool endpoint
    3. Orchestrator calls wait_for_turn_end() which blocks
    4. Orchestrator calls get_turn_result() to get actions
    """

    def __init__(self, host: str = "localhost", port: int = 8765, turn_timeout: float = 300.0):
        self.host = host
        self.port = port
        self.mcp_server = CivMCPServer(turn_timeout=turn_timeout)
        self.http_server: Optional[HTTPServer] = None
        self.thread: Optional[Thread] = None

    def start(self):
        """Start the HTTP server in a background thread."""
        MCPHTTPHandler.mcp_server = self.mcp_server

        self.http_server = HTTPServer((self.host, self.port), MCPHTTPHandler)
        self.thread = Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()

        logger.info(f"MCP HTTP Server started on http://{self.host}:{self.port}")
        logger.info(f"Endpoints: /health, /state, /tools, /tool")

    def stop(self):
        """Stop the HTTP server."""
        if self.http_server:
            self.http_server.shutdown()
            logger.info("MCP HTTP Server stopped")

    def start_turn(self, state: dict) -> None:
        """Start a new turn - called by orchestrator when DLL signals turn."""
        self.mcp_server.start_turn(state)

    def wait_for_turn_end(self, timeout: Optional[float] = None) -> bool:
        """Block until LLM calls end_turn or timeout. Returns True if ended normally."""
        return self.mcp_server.wait_for_turn_end(timeout)

    def get_turn_result(self) -> tuple[list, str]:
        """Get (actions, notes) from the completed turn."""
        return self.mcp_server.get_turn_result()


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
