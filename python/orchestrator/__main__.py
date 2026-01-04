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
import os
import sys
from threading import Thread
from typing import TYPE_CHECKING, Any

from .formatting import format_game_state
from .mcp_http_server import MCPHTTPServer
from .pipe_server import NamedPipeServer
from .state_db import StateDatabase
from .notification_handler import NotificationHandler

if TYPE_CHECKING:
    from .pipe_server import PipeConnection


DEFAULT_PIPE = r"\\.\pipe\civv_llm"


def run_debug_server(pipe_path: str, raw_mode: bool = False) -> None:
    """Run a debug pipe server that displays incoming messages (read-only)."""
    import json

    print("=" * 60)
    print("Civ V LLM Bridge - Debug Mode (read-only)")
    print("=" * 60)
    print(f"Pipe: {pipe_path}")
    print(f"Mode: {'raw JSON' if raw_mode else 'formatted'}")
    print("Waiting for DLL to connect...")
    print("=" * 60)
    print()

    def on_turn_start(state: dict[str, Any], pipe_conn: "PipeConnection") -> None:
        if raw_mode:
            print(json.dumps(state, indent=2), flush=True)
        else:
            print(format_game_state(state), flush=True)
        # Debug mode: don't send any actions, just display

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
    once: bool = False,
    dashboard_host: str | None = None,
    dashboard_port: int = 5000,
) -> None:
    """Run in MCP mode: LLM controls the game via HTTP tool calls.

    Sequential flow per turn:
    1. DLL sends turn_start with state
    2. Orchestrator exposes state to LLM via MCP HTTP server
    3. LLM sends actions one at a time, each goes to DLL immediately
    4. LLM calls end_turn when done
    5. DLL advances to next turn
    """
    # Initialize state database and notification handler
    state_db = StateDatabase()
    notification_handler = NotificationHandler()
    
    # Register callback to save notifications to database
    def save_notification(notif_type: str, message: str, data: dict[str, Any] | None) -> None:
        state_db.add_notification(notif_type, message, data)
    notification_handler.register_callback(save_notification)
    
    # Start MCP HTTP server with state tracking
    mcp_server = MCPHTTPServer(
        mcp_host,
        mcp_port,
        turn_timeout=turn_timeout,
        state_db=state_db,
        notification_handler=notification_handler
    )
    mcp_server.start()

    print(f"[orchestrator] MCP server: http://{mcp_host}:{mcp_port}/tool", file=sys.stderr)
    print(f"[orchestrator] Turn timeout: {turn_timeout}s", file=sys.stderr)
    print(f"[orchestrator] State database: {state_db.db_path}", file=sys.stderr)

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
        """Called when DLL sends turn_start. Blocks until LLM calls end_turn."""
        turn_num = state.get("turn", "?")
        print(f"[orchestrator] Turn {turn_num}: received state, waiting for LLM...", file=sys.stderr)

        # Start turn - expose state and pipe connection to MCP server
        mcp_server.mcp_server.start_turn(state, pipe_conn)

        # Wait for LLM to call end_turn (blocks here)
        ended_normally = mcp_server.mcp_server.wait_for_turn_end()

        if not ended_normally:
            print(f"[orchestrator] Turn {turn_num}: TIMEOUT", file=sys.stderr)
        else:
            print(f"[orchestrator] Turn {turn_num}: completed", file=sys.stderr)

    # Create pipe server with state tracking and run in background thread
    pipe_server = NamedPipeServer(
        pipe_path,
        on_turn_start,
        state_db=state_db,
        notification_handler=notification_handler
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
    parser = argparse.ArgumentParser(
        description="Civ V LLM Orchestrator - bridges DLL and LLM via MCP"
    )

    # Pipe options
    parser.add_argument("--pipe", default=DEFAULT_PIPE,
                        help=f"Named pipe path (default: {DEFAULT_PIPE})")
    parser.add_argument("--once", action="store_true",
                        help="Process one turn then exit")

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
    parser.add_argument("--raw", action="store_true",
                        help="In debug mode, show raw JSON")

    args = parser.parse_args()

    # Standalone dashboard mode
    if args.dashboard_only:
        run_standalone_dashboard(args.dashboard_host, args.dashboard_port)
        return

    # Debug mode (read-only viewer)
    if args.debug:
        run_debug_server(args.pipe, raw_mode=args.raw)
        return

    # Default: MCP mode
    pipe = args.pipe or os.environ.get("CIVV_PIPE") or DEFAULT_PIPE
    run_mcp_mode(
        pipe_path=pipe,
        mcp_host=args.mcp_host,
        mcp_port=args.mcp_port,
        turn_timeout=args.turn_timeout,
        once=args.once,
        dashboard_host=args.dashboard_host if args.dashboard else None,
        dashboard_port=args.dashboard_port,
    )


if __name__ == "__main__":
    main()
