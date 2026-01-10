"""
Civ V LLM Orchestrator

Bridges the Civ V DLL (named pipe) and LLM control.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from threading import Thread

from .logging_setup import setup_logging
from .mcp_http_server import MCPHTTPServer
from .mcp_server import CivMCPServer
from .pipe_server import NamedPipeServer


DEFAULT_PIPE = r"\\.\pipe\civv_llm"


def run_mcp_mode(
    pipe_path: str,
    mcp_host: str,
    mcp_port: int,
    turn_timeout: float,
    dashboard_host: str | None = None,
    dashboard_port: int = 5000,
) -> None:
    # Create the central game server (single source of truth for all state)
    mcp_server = CivMCPServer(turn_timeout=turn_timeout)

    # Create HTTP server (just exposes mcp_server via HTTP)
    http_server = MCPHTTPServer(mcp_host, mcp_port, mcp_server=mcp_server)
    http_server.start()

    # Create pipe server (handles DLL communication, calls mcp_server on events)
    pipe_server = NamedPipeServer(pipe_path, mcp_server=mcp_server)

    print(f"[orchestrator] MCP server: http://{mcp_host}:{mcp_port}/tool", file=sys.stderr)
    print(f"[orchestrator] Turn timeout: {turn_timeout}s", file=sys.stderr)
    print(f"[orchestrator] Pipe: {pipe_path}", file=sys.stderr)

    # Start dashboard if requested
    if dashboard_host is not None:
        from .dashboard import create_dashboard_app

        app = create_dashboard_app(mcp_server)

        def run_dashboard():
            import logging
            log = logging.getLogger("werkzeug")
            log.setLevel(logging.WARNING)
            app.run(host=dashboard_host, port=dashboard_port, threaded=True, use_reloader=False)

        dashboard_thread = Thread(target=run_dashboard, daemon=True)
        dashboard_thread.start()
        print(f"[orchestrator] Dashboard: http://{dashboard_host}:{dashboard_port}", file=sys.stderr)

    print(f"[orchestrator] Waiting for DLL to connect...", file=sys.stderr)

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
    parser.add_argument("--turn-timeout", type=float, default=300.0,
                        help="Max seconds to wait for LLM per turn (default: 300)")

    # Dashboard options
    parser.add_argument("--disable-dashboard", action="store_true",
                        help="Start the monitoring dashboard")
    parser.add_argument("--dashboard-host", default="0.0.0.0",
                        help="Dashboard host (default: 0.0.0.0)")
    parser.add_argument("--dashboard-port", type=int, default=5000,
                        help="Dashboard port (default: 5000)")

    args = parser.parse_args()

    # Default: MCP mode
    pipe = args.pipe or os.environ.get("CIVV_PIPE") or DEFAULT_PIPE
    run_mcp_mode(
        pipe_path=pipe,
        mcp_host=args.mcp_host,
        mcp_port=args.mcp_port,
        turn_timeout=args.turn_timeout,
        dashboard_host=args.dashboard_host if not args.disable_dashboard else None,
        dashboard_port=args.dashboard_port,
    )

if __name__ == "__main__":
    main()
