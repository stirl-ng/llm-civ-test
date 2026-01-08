"""
Civ V LLM Orchestrator

Bridges the Civ V DLL (named pipe) and LLM control.

Modes:
- Default: MCP mode - creates pipe, waits for DLL, LLM controls via HTTP
- --debug: Display pipe messages without processing (for troubleshooting)
- --dashboard: Add the Flask monitoring dashboard
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from threading import Thread
from typing import TYPE_CHECKING, Any

from .logging_setup import setup_logging
from .mcp_http_server import MCPHTTPServer
from .pipe_server import NamedPipeServer

if TYPE_CHECKING:
    from .pipe_server import PipeConnection


DEFAULT_PIPE = r"\\.\pipe\civv_llm"


def run_debug_server(pipe_path: str) -> None:
    """Run a debug pipe server that displays incoming messages (read-only)."""
    import json

    print("=" * 60)
    print("Civ V LLM Bridge - Debug Mode (read-only)")
    print("=" * 60)
    print(f"Pipe: {pipe_path}")
    print("Waiting for DLL to connect...")
    print("=" * 60)
    print()

    def on_turn_start(state: dict[str, Any], pipe_conn: "PipeConnection") -> None:
        # Debug mode: don't send any actions, just display raw JSON
        print(json.dumps(state, indent=2), flush=True)

    server = NamedPipeServer(pipe_path, on_turn_start)
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nExiting.", flush=True)
        server.stop()


def run_mcp_mode(
    pipe_path: str,
    mcp_host: str,
    mcp_port: int,
    turn_timeout: float,
    dashboard_host: str | None = None,
    dashboard_port: int = 5000,
) -> None:
    """Run the orchestrator with interactive MCP protocol.

    Sequential flow per turn:
    1. DLL sends turn_start with state
    2. Orchestrator exposes state to LLM via MCP HTTP server
    3. LLM sends actions one at a time, each goes to DLL immediately
    4. LLM calls end_turn when done
    5. DLL advances to next turn
    """
    # Start MCP HTTP server
    mcp_server = MCPHTTPServer(
        mcp_host,
        mcp_port,
        turn_timeout=turn_timeout
    )
    mcp_server.start()

    print(f"[orchestrator] MCP server: http://{mcp_host}:{mcp_port}/tool", file=sys.stderr)
    print(f"[orchestrator] Turn timeout: {turn_timeout}s", file=sys.stderr)

    # Start dashboard if requested
    if dashboard_host is not None:
        from .dashboard import create_dashboard_app, setup_dashboard_logging

        setup_dashboard_logging()
        app = create_dashboard_app(mcp_server.mcp_server)

        def run_dashboard():
            import logging
            log = logging.getLogger("werkzeug")
            log.setLevel(logging.WARNING)
            app.run(host=dashboard_host, port=dashboard_port, threaded=True, use_reloader=False)

        dashboard_thread = Thread(target=run_dashboard, daemon=True)
        dashboard_thread.start()
        print(f"[orchestrator] Dashboard: http://{dashboard_host}:{dashboard_port}", file=sys.stderr)

    print(f"[orchestrator] Pipe: {pipe_path}", file=sys.stderr)
    print(f"[orchestrator] Waiting for DLL to connect...", file=sys.stderr)

    def on_turn_start(state: dict[str, Any], pipe_conn: "PipeConnection") -> None:
        """Called when DLL sends turn_start. Updates state and returns immediately."""
        turn_num = state.get("turn", "?")
        print(f"[orchestrator] Turn {turn_num}: received state", file=sys.stderr)

        # Update turn state - expose pipe connection to MCP server
        mcp_server.mcp_server.start_turn(state, pipe_conn)

    # Create pipe server and run in background thread
    pipe_server = NamedPipeServer(
        pipe_path,
        on_turn_start
    )

    pipe_thread = Thread(target=pipe_server.start, daemon=True)
    pipe_thread.start()

    # Main thread waits for Ctrl+C
    try:
        while pipe_thread.is_alive():
            pipe_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n[orchestrator] Shutting down...", file=sys.stderr)
    finally:
        pipe_server.stop()
        mcp_server.stop()


def run_standalone_dashboard(host: str, port: int) -> None:
    """Run just the dashboard without pipe/MCP (for UI testing)."""
    from .dashboard import run_dashboard

    print(f"[orchestrator] Standalone dashboard mode", file=sys.stderr)
    print(f"[orchestrator] Note: MCP commands will fail (no MCP server)", file=sys.stderr)
    run_dashboard(host=host, port=port)


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
    parser.add_argument("--turn-timeout", type=float, default=300.0,
                        help="Max seconds to wait for LLM per turn (default: 300)")

    # Dashboard options
    parser.add_argument("--dashboard", action="store_true",
                        help="Start the monitoring dashboard")
    parser.add_argument("--dashboard-host", default="0.0.0.0",
                        help="Dashboard host (default: 0.0.0.0)")
    parser.add_argument("--dashboard-port", type=int, default=5000,
                        help="Dashboard port (default: 5000)")
    parser.add_argument("--dashboard-only", action="store_true",
                        help="Run only the dashboard (for UI testing)")

    # Debug options
    parser.add_argument("--debug", action="store_true",
                        help="Debug mode: display messages only (read-only)")

    args = parser.parse_args()

    # Standalone dashboard mode
    if args.dashboard_only:
        run_standalone_dashboard(args.dashboard_host, args.dashboard_port)
        return

    # Debug mode (read-only viewer)
    if args.debug:
        run_debug_server(args.pipe)
        return

    # Default: MCP mode
    pipe = args.pipe or os.environ.get("CIVV_PIPE") or DEFAULT_PIPE
    run_mcp_mode(
        pipe_path=pipe,
        mcp_host=args.mcp_host,
        mcp_port=args.mcp_port,
        turn_timeout=args.turn_timeout,
        dashboard_host=args.dashboard_host if args.dashboard else None,
        dashboard_port=args.dashboard_port,
    )


if __name__ == "__main__":
    main()
