"""
Civ V LLM Orchestrator

Bridges the Civ V DLL (named pipe) and LLM control via MCP HTTP.

The orchestrator:
1. Connects to the DLL via named pipe
2. Starts an HTTP server for LLM tool calls
3. For each turn:
   - Receives turn_start from DLL
   - Waits for LLM to make decisions via HTTP
   - Forwards actions to DLL, returns results
   - Ends turn when LLM calls end_turn
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
from typing import Optional

from .formatting import format_message
from .mcp_http_server import MCPHTTPServer
from .pipe_server import NamedPipeServer
from .turn_manager import TurnManager

logger = logging.getLogger(__name__)


class Transport:
    """Abstract transport for DLL communication."""

    def read_line(self) -> Optional[str]:
        raise NotImplementedError

    def write_line(self, s: str) -> None:
        raise NotImplementedError


class StdIOTransport(Transport):
    """Transport using stdin/stdout (for testing)."""

    def __init__(self):
        self.reader = sys.stdin
        self.writer = sys.stdout

    def read_line(self) -> Optional[str]:
        return self.reader.readline()

    def write_line(self, s: str) -> None:
        self.writer.write(s)
        if not s.endswith("\n"):
            self.writer.write("\n")
        self.writer.flush()


class WindowsPipeTransport(Transport):
    """Transport using Windows named pipe."""

    def __init__(self, pipe_name: str, retry_seconds: float = 0.5, timeout: float = 30.0):
        self.pipe_name = pipe_name
        deadline = time.time() + timeout
        last_err: Optional[Exception] = None
        fh: Optional[io.BufferedRandom] = None

        while time.time() < deadline:
            try:
                raw = open(pipe_name, mode="r+b", buffering=0)
                fh = io.BufferedRandom(raw)
                break
            except Exception as e:
                last_err = e
                time.sleep(retry_seconds)

        if fh is None:
            raise RuntimeError(f"Failed to open pipe {pipe_name}: {last_err}")
        self.fh = fh

    def read_line(self) -> Optional[str]:
        data = self.fh.readline()
        if not data:
            return None
        try:
            return data.decode("utf-8")
        except Exception:
            return data.decode("utf-8", errors="replace")

    def write_line(self, s: str) -> None:
        if not s.endswith("\n"):
            s = s + "\n"
        self.fh.write(s.encode("utf-8"))
        self.fh.flush()


DEFAULT_DEBUG_PIPE = r"\\.\pipe\CivVPGameState"
DEFAULT_PIPE = r"\\.\pipe\civv_llm"


def run_debug_server(pipe_path: str, raw_mode: bool = False) -> None:
    """Run a debug pipe server that displays incoming messages."""
    print("=" * 60)
    print("Civ V LLM Bridge - Debug Mode")
    print("=" * 60)
    print(f"Pipe: {pipe_path}")
    print(f"Mode: {'raw JSON' if raw_mode else 'formatted'}")
    print("=" * 60)
    print()

    def on_message(data: bytes) -> Optional[bytes]:
        try:
            decoded = data.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError:
            decoded = data.hex()
        output = format_message(decoded, raw_mode=raw_mode)
        print(output, flush=True)
        return None

    server = NamedPipeServer(pipe_path, on_message)
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nExiting.", flush=True)
        server.stop()


def run_orchestrator(
    transport: Transport,
    mcp_host: str,
    mcp_port: int,
    turn_timeout: float,
    once: bool = False,
) -> None:
    """Run the orchestrator with interactive MCP protocol.

    Flow:
    1. Wait for turn_start from DLL
    2. Start turn, expose state via MCP HTTP
    3. LLM makes tool calls (queries + actions)
    4. LLM calls end_turn
    5. Repeat for next turn
    """
    # Create turn manager with transport
    turn_manager = TurnManager(transport, action_timeout=30.0)

    # Start MCP HTTP server
    mcp_server = MCPHTTPServer(turn_manager, mcp_host, mcp_port)
    mcp_server.start()

    print(f"[orchestrator] MCP server: http://{mcp_host}:{mcp_port}", file=sys.stderr)
    print(f"[orchestrator] Waiting for DLL...", file=sys.stderr)

    try:
        while True:
            # Read message from DLL
            line = transport.read_line()
            if line is None or line == "":
                print("[orchestrator] DLL disconnected", file=sys.stderr)
                break

            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from DLL: {e}")
                continue

            msg_type = msg.get("type")

            if msg_type == "turn_start":
                # Start new turn
                turn_num = msg.get("turn", "?")
                player_id = msg.get("player_id", "?")
                print(f"[orchestrator] Turn {turn_num} for player {player_id}", file=sys.stderr)

                turn_manager.start_turn(msg)

                # Wait for LLM to end turn (or timeout)
                ended = turn_manager.wait_for_turn_end(timeout=turn_timeout)

                if not ended:
                    print(f"[orchestrator] Turn {turn_num} timed out", file=sys.stderr)

                print(f"[orchestrator] Turn {turn_num} complete", file=sys.stderr)

                if once:
                    break

            else:
                logger.warning(f"Unexpected message type: {msg_type}")

    except KeyboardInterrupt:
        print("\n[orchestrator] Interrupted", file=sys.stderr)
    finally:
        mcp_server.stop()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Civ V LLM Orchestrator - bridges DLL and LLM via MCP HTTP"
    )

    # Transport options
    parser.add_argument("--pipe", help="Named pipe path")
    parser.add_argument("--stdio", action="store_true", help="Use stdin/stdout (testing)")
    parser.add_argument("--once", action="store_true", help="Process one turn then exit")

    # MCP server options
    parser.add_argument("--mcp-host", default="localhost", help="MCP server host")
    parser.add_argument("--mcp-port", type=int, default=8765, help="MCP server port")
    parser.add_argument("--turn-timeout", type=float, default=300.0,
                        help="Max seconds per turn (default: 300)")

    # Debug options
    parser.add_argument("--debug", action="store_true", help="Debug mode: display messages only")
    parser.add_argument("--raw", action="store_true", help="In debug mode, show raw JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Debug mode
    if args.debug:
        pipe = args.pipe or DEFAULT_DEBUG_PIPE
        run_debug_server(pipe, raw_mode=args.raw)
        return

    # Set up transport
    if args.stdio:
        transport: Transport = StdIOTransport()
        print("[orchestrator] Using stdio transport", file=sys.stderr)
    else:
        pipe = args.pipe or os.environ.get("CIVV_PIPE") or DEFAULT_PIPE
        print(f"[orchestrator] Connecting to pipe: {pipe}", file=sys.stderr)
        transport = WindowsPipeTransport(pipe)
        print(f"[orchestrator] Connected", file=sys.stderr)

    # Run orchestrator
    run_orchestrator(
        transport=transport,
        mcp_host=args.mcp_host,
        mcp_port=args.mcp_port,
        turn_timeout=args.turn_timeout,
        once=args.once,
    )


if __name__ == "__main__":
    main()
