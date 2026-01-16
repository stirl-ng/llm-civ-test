"""
Civ V LLM Orchestrator

Bridges the Civ V DLL (named pipe) and LLM control.
"""
from __future__ import annotations

import argparse
import os
import sys
from threading import Thread

from .logging_setup import setup_logging
from .mcp_http_server import MCPHTTPServer
from .mcp_server import CivMCPServer
from .pipe_server import NamedPipeServer
from .game_state import GameState


DEFAULT_PIPE = r"\\.\pipe\civv_llm"


def run_mcp_mode(
    pipe_path: str,
    mcp_host: str,
    mcp_port: int,
) -> None:
    """Run the orchestrator in MCP mode.

    Creates:
    - GameState: Single source of truth for game metadata
    - NamedPipeServer: Handles pipe connection, message processing, logging
    - CivMCPServer: Tool executor for LLM actions
    - MCPHTTPServer: HTTP wrapper for CivMCPServer
    """
    # Create GameState instance (single source of truth for metadata)
    game_state = GameState()

    # Create pipe server (manages pipe connection, message processing, logging)
    # Pass game_state so it can update metadata from DLL messages
    pipe_server = NamedPipeServer(pipe_path, game_state=game_state)

    # Create the MCP server with send_request callback and game_state
    def send_request(request: dict, timeout: float) -> dict:
        """Send a request to the DLL via the pipe server."""
        return pipe_server.send_request(request, timeout)

    mcp_server = CivMCPServer(
        send_request=send_request,
        game_state=game_state
    )

    # Start pipe server in background thread
    pipe_thread = Thread(target=pipe_server.start, daemon=True)
    pipe_thread.start()

    print(f"[orchestrator] Waiting for DLL to connect...", file=sys.stderr)

    # Wait for pipe connection to be established
    pipe_connection = pipe_server.get_pipe_connection(timeout=None)  # Wait indefinitely
    if pipe_connection:
        print(f"[orchestrator] DLL connected", file=sys.stderr)

    # Create HTTP server (just exposes mcp_server via HTTP)
    http_server = MCPHTTPServer(mcp_host, mcp_port, mcp_server=mcp_server)
    http_server.start()

    print(f"[orchestrator] MCP server: http://{mcp_host}:{mcp_port}/tool", file=sys.stderr)
    print(f"[orchestrator] Pipe: {pipe_path}", file=sys.stderr)

    # Main thread waits for Ctrl+C
    try:
        while pipe_thread.is_alive():
            pipe_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n[orchestrator] Shutting down...", file=sys.stderr)
    finally:
        pipe_server.stop()
        http_server.stop()


def main() -> None:
    # Setup logging first (before any other imports that might log)
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Civ V LLM Orchestrator - bridges DLL and LLM via MCP HTTP"
    )

    # Pipe options
    parser.add_argument("--pipe", default=DEFAULT_PIPE,
                        help=f"Named pipe path (default: {DEFAULT_PIPE})")

    # MCP options
    parser.add_argument("--mcp-host", default="localhost",
                        help="MCP server host (default: localhost)")
    parser.add_argument("--mcp-port", type=int, default=8765,
                        help="MCP server port (default: 8765)")

    args = parser.parse_args()

    # Run MCP mode
    pipe = args.pipe or os.environ.get("CIVV_PIPE") or DEFAULT_PIPE
    run_mcp_mode(
        pipe_path=pipe,
        mcp_host=args.mcp_host,
        mcp_port=args.mcp_port,
    )


if __name__ == "__main__":
    main()
