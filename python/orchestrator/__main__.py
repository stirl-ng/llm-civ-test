"""
Civ V LLM Orchestrator

Bridges the Civ V DLL (named pipe) and LLM control.

Modes:
- --mcp: Turn-based MCP mode. LLM connects via HTTP, makes decisions, calls end_turn.
- --debug: Display pipe messages without processing (for debugging)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from typing import Optional

from .formatting import format_message
from .mcp_http_server import MCPHTTPServer
from .pipe_server import NamedPipeServer


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
    """Transport using Windows named pipe (connects to existing pipe)."""

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


def run_mcp_mode(
    transport: Transport,
    mcp_host: str,
    mcp_port: int,
    turn_timeout: float,
    once: bool = False,
) -> None:
    """Run in MCP mode: LLM controls the game via HTTP tool calls.

    Flow per turn:
    1. Receive state from DLL
    2. Start turn (expose state to LLM via MCP)
    3. Wait for LLM to call end_turn (or timeout)
    4. Send queued actions back to DLL
    """
    # Start MCP HTTP server
    mcp_server = MCPHTTPServer(mcp_host, mcp_port, turn_timeout=turn_timeout)
    mcp_server.start()

    print(f"[orchestrator] MCP mode active", file=sys.stderr)
    print(f"[orchestrator] LLM endpoint: http://{mcp_host}:{mcp_port}/tool", file=sys.stderr)
    print(f"[orchestrator] Turn timeout: {turn_timeout}s", file=sys.stderr)

    try:
        while True:
            # 1. Read state from DLL
            line = transport.read_line()
            if line is None or line == "":
                print("[orchestrator] Pipe closed", file=sys.stderr)
                break

            line = line.strip()
            if not line:
                continue

            try:
                state = json.loads(line)
            except json.JSONDecodeError as e:
                err = {"error": "invalid_json", "detail": str(e)}
                transport.write_line(json.dumps(err))
                continue

            turn_num = state.get("data", {}).get("turn", "?")
            print(f"[orchestrator] Turn {turn_num}: waiting for LLM...", file=sys.stderr)

            # 2. Start turn - expose state to LLM
            mcp_server.start_turn(state)

            # 3. Wait for LLM to call end_turn
            ended_normally = mcp_server.wait_for_turn_end()

            # 4. Get queued actions
            actions, notes = mcp_server.get_turn_result()

            if not ended_normally:
                notes = f"TIMEOUT - {notes}" if notes else "TIMEOUT"

            # 5. Build response for DLL
            response = {
                "turn": turn_num,
                "actions": actions,
                "notes": notes,
            }

            print(f"[orchestrator] Turn {turn_num}: sending {len(actions)} actions", file=sys.stderr)
            transport.write_line(json.dumps(response))

            if once:
                break

    except KeyboardInterrupt:
        print("\n[orchestrator] Interrupted", file=sys.stderr)
    finally:
        mcp_server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Civ V LLM Orchestrator - bridges DLL and LLM via MCP"
    )
    parser.add_argument("--pipe", help="Named pipe path")
    parser.add_argument("--stdio", action="store_true", help="Use stdin/stdout (testing)")
    parser.add_argument("--once", action="store_true", help="Process one turn then exit")

    # MCP options
    parser.add_argument("--mcp", action="store_true", help="Run in MCP mode (LLM via HTTP)")
    parser.add_argument("--mcp-host", default="localhost", help="MCP server host")
    parser.add_argument("--mcp-port", type=int, default=8765, help="MCP server port")
    parser.add_argument("--turn-timeout", type=float, default=300.0,
                        help="Max seconds to wait for LLM per turn (default: 300)")

    # Debug options
    parser.add_argument("--debug", action="store_true", help="Debug mode: display messages only")
    parser.add_argument("--raw", action="store_true", help="In debug mode, show raw JSON")

    args = parser.parse_args()

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
        transport = WindowsPipeTransport(pipe)
        print(f"[orchestrator] Connected to pipe: {pipe}", file=sys.stderr)

    # MCP mode (default and only real mode now)
    if args.mcp or True:  # Always MCP mode for now
        run_mcp_mode(
            transport=transport,
            mcp_host=args.mcp_host,
            mcp_port=args.mcp_port,
            turn_timeout=args.turn_timeout,
            once=args.once,
        )
    else:
        print("[orchestrator] Error: --mcp mode required", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
