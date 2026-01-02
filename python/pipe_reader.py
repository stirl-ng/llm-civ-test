#!/usr/bin/env python3
"""
Named pipe server for receiving Civ V game state from the LLM bridge DLL.

This utility:
- Creates a named pipe server
- Receives JSON messages from the Civ V DLL
- Parses and pretty-prints game state information
- Can be extended to forward state to an LLM orchestrator
"""

from __future__ import annotations

import argparse
import json
import threading
from typing import Optional, Any

import pywintypes
import win32file
import win32pipe
import time


DEFAULT_PIPE = r"\\.\pipe\CivVPGameState"
BUFFER_SIZE = 64 * 1024  # 64KB to handle larger game state payloads


def format_game_state(data: dict[str, Any]) -> str:
    """Format game state data for human-readable display."""
    lines = []

    kind = data.get("kind", "unknown")
    category = data.get("category", "")

    if kind == "state" and category == "game_level":
        game_data = data.get("data", {})
        lines.append("=" * 60)
        lines.append("GAME LEVEL STATE")
        lines.append("=" * 60)
        lines.append(f"  Turn:        {game_data.get('turn', '?')}")
        lines.append(f"  Game Speed:  {game_data.get('game_speed', '?')}")
        lines.append(f"  Difficulty:  {game_data.get('difficulty', '?')}")
        lines.append(f"  Era:         {game_data.get('era', '?')}")
        lines.append(f"  Map Size:    {game_data.get('map_size', '?')}")
        lines.append(f"  Map Type:    {game_data.get('map_type', '?')}")
        lines.append(f"  Sea Level:   {game_data.get('sea_level', '?')}")
        lines.append(f"  Players:     {game_data.get('players_alive', '?')} alive / {game_data.get('civs_ever', '?')} ever")

        victory_conds = game_data.get("victory_conditions", [])
        if victory_conds:
            lines.append(f"  Victory:     {', '.join(victory_conds)}")

        victory_progress = game_data.get("victory_progress", {})
        if victory_progress:
            lines.append("")
            lines.append("  Victory Progress:")
            for vtype, vprog in victory_progress.items():
                if isinstance(vprog, dict):
                    prog_str = ", ".join(f"{k}={v}" for k, v in vprog.items())
                    lines.append(f"    {vtype}: {prog_str}")

        lines.append("=" * 60)
    else:
        # Unknown format, just pretty-print
        lines.append(f"Received {kind} message:")
        lines.append(json.dumps(data, indent=2))

    return "\n".join(lines)


def process_message(raw: str) -> None:
    """Process a received message and display it."""
    try:
        data = json.loads(raw)
        formatted = format_game_state(data)
        print(formatted, flush=True)
    except json.JSONDecodeError as e:
        print(f"[warn] Invalid JSON: {e}", flush=True)
        print(f"  Raw: {raw[:200]}...", flush=True)


def create_server_pipe(path: str) -> pywintypes.HANDLEType:
    """Create a named pipe server for bidirectional communication.

    The pipe is created in duplex mode to allow:
    - Receiving game state from the DLL
    - Sending actions back to the DLL (future)
    """
    return win32pipe.CreateNamedPipe(
        path,
        win32pipe.PIPE_ACCESS_DUPLEX,  # Bidirectional for future action sending
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
        1,
        BUFFER_SIZE,
        BUFFER_SIZE,
        0,
        None,
    )


def wait_for_client(handle: pywintypes.HANDLEType, poll_seconds: float = 0.1) -> None:
    """Wait for a client connection while remaining responsive to Ctrl+C."""

    connected = threading.Event()
    exc_holder: list[BaseException] = []

    def _connector() -> None:
        try:
            win32pipe.ConnectNamedPipe(handle, None)
        except BaseException as exc:  # Capture pywin errors or KeyboardInterrupt.
            exc_holder.append(exc)
        finally:
            connected.set()

    thread = threading.Thread(target=_connector, name="pipe-connector", daemon=True)
    thread.start()

    try:
        while not connected.wait(timeout=poll_seconds):
            pass
    except KeyboardInterrupt:
        try:
            win32pipe.DisconnectNamedPipe(handle)
        except pywintypes.error:
            pass
        finally:
            thread.join(timeout=1)
        raise

    thread.join()

    if not exc_holder:
        return
    exc = exc_holder[0]
    if isinstance(exc, pywintypes.error) and exc.winerror == 535:  # ERROR_PIPE_CONNECTED
        return
    raise exc


def stream_pipe(handle: pywintypes.HANDLEType, poll_seconds: float = 0.05, raw_mode: bool = False) -> None:
    """Read and process messages from the pipe.

    Args:
        handle: The pipe handle to read from
        poll_seconds: How often to poll for data
        raw_mode: If True, print raw JSON; if False, format nicely
    """
    while True:
        try:
            peek = win32pipe.PeekNamedPipe(handle, 0)
        except pywintypes.error as exc:
            if exc.winerror in {109, 233}:  # ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED
                break
            raise
        if isinstance(peek, tuple):
            if len(peek) >= 3:
                available = peek[2]
            elif len(peek) >= 2:
                available = peek[1]
            else:
                available = 0
        else:
            available = int(peek)
        if available == 0:
            time.sleep(poll_seconds)
            continue
        to_read = min(BUFFER_SIZE, available)
        try:
            _, data = win32file.ReadFile(handle, to_read)
        except pywintypes.error as exc:
            if exc.winerror == 109:  # ERROR_BROKEN_PIPE
                break
            raise
        if not data:
            break
        try:
            decoded = data.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError:
            decoded = data.hex()

        if raw_mode:
            print(decoded, flush=True)
        else:
            process_message(decoded)


def serve_forever(path: str, raw_mode: bool = False) -> None:
    """Run the pipe server, accepting connections and processing messages.

    Args:
        path: The named pipe path to create
        raw_mode: If True, print raw JSON instead of formatted output
    """
    while True:
        print(f"Creating pipe server at {path!r} ...", flush=True)
        handle: Optional[pywintypes.HANDLEType] = create_server_pipe(path)
        restart = True
        try:
            print("Waiting for LLMBridge DLL to connect ...", flush=True)
            wait_for_client(handle)
            print("Client connected. Streaming messages (Ctrl+C to stop).", flush=True)
            stream_pipe(handle, raw_mode=raw_mode)
        except KeyboardInterrupt:
            print("\nCtrl+C pressed. Exiting reader.", flush=True)
            restart = False
            raise
        finally:
            win32file.CloseHandle(handle)
            if restart:
                print("Client disconnected. Restarting server ...", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Named pipe server for receiving Civ V game state from LLMBridge."
    )
    parser.add_argument(
        "--pipe",
        default=DEFAULT_PIPE,
        help=f"Pipe path to host (default: {DEFAULT_PIPE})"
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw JSON instead of formatted output"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Civ V LLM Bridge - Pipe Reader")
    print("=" * 60)
    print(f"Pipe: {args.pipe}")
    print(f"Mode: {'raw JSON' if args.raw else 'formatted'}")
    print("=" * 60)
    print()

    serve_forever(args.pipe, raw_mode=args.raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
