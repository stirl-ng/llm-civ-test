"""Named pipe server for communication with Civ V DLL.

Handles bidirectional communication:
- Incoming: DLL → Python (events, responses)
- Outgoing: Python → DLL (commands, queries)
"""

from __future__ import annotations

import ctypes
import json
import logging
import queue
import threading
import time
import uuid
from ctypes import wintypes
from typing import TYPE_CHECKING, Any, Optional

from .message_logger import get_message_logger

if TYPE_CHECKING:
    from .game_state import GameState

logger = logging.getLogger(__name__)

# Windows API constants and bindings
LPSECURITY_ATTRIBUTES = ctypes.c_void_p


class WinAPI:
    """Windows API bindings for named pipes."""

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    PIPE_ACCESS_DUPLEX = 0x00000003
    PIPE_TYPE_MESSAGE = 0x00000004
    PIPE_READMODE_MESSAGE = 0x00000002
    PIPE_WAIT = 0x00000000

    ERROR_PIPE_CONNECTED = 535
    ERROR_MORE_DATA = 234

    BUFSIZE = 64 * 1024

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    CreateNamedPipeW = kernel32.CreateNamedPipeW
    CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, LPSECURITY_ATTRIBUTES,
    ]
    CreateNamedPipeW.restype = wintypes.HANDLE

    ConnectNamedPipe = kernel32.ConnectNamedPipe
    ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    ConnectNamedPipe.restype = wintypes.BOOL

    SetNamedPipeHandleState = kernel32.SetNamedPipeHandleState
    SetNamedPipeHandleState.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p
    ]
    SetNamedPipeHandleState.restype = wintypes.BOOL

    ReadFile = kernel32.ReadFile
    ReadFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
    ]
    ReadFile.restype = wintypes.BOOL

    WriteFile = kernel32.WriteFile
    WriteFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
    ]
    WriteFile.restype = wintypes.BOOL

    FlushFileBuffers = kernel32.FlushFileBuffers
    FlushFileBuffers.argtypes = [wintypes.HANDLE]
    FlushFileBuffers.restype = wintypes.BOOL

    PeekNamedPipe = kernel32.PeekNamedPipe
    PeekNamedPipe.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD)
    ]
    PeekNamedPipe.restype = wintypes.BOOL

    DisconnectNamedPipe = kernel32.DisconnectNamedPipe
    DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    DisconnectNamedPipe.restype = wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    CancelIoEx = kernel32.CancelIoEx
    CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    CancelIoEx.restype = wintypes.BOOL


class PipeConnection:
    """Thread-safe wrapper for pipe I/O.

    Handles:
    - Writing requests to the pipe
    - Matching responses to pending requests via request_id
    - Thread-safe coordination between pipe reader and HTTP handler
    """

    def __init__(self, handle: int):
        self._handle = handle
        self._lock = threading.Lock()
        self._buf = (ctypes.c_char * WinAPI.BUFSIZE)()

        # Pending request → response queue mapping
        self._pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()

    def send_request(
        self,
        request: dict[str, Any],
        timeout: float = 5.0
    ) -> dict[str, Any]:
        """Send a request to the DLL and wait for response.

        Thread-safe: can be called from HTTP handler thread.

        Args:
            request: Request dict (must have 'type' field)
            timeout: Seconds to wait for response

        Returns:
            Response dict from DLL
        """
        # Ensure request has an ID for response matching
        request_id = request.get("request_id") or str(uuid.uuid4())
        request["request_id"] = request_id

        # Log outgoing request
        get_message_logger().log(request, direction="outgoing")

        # Create response queue
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._pending_lock:
            self._pending[request_id] = response_queue

        try:
            # Write to pipe
            with self._lock:
                data = json.dumps(request).encode("utf-8") + b"\n"
                if not self._write(data):
                    return {"error": "Pipe write failed", "status": "error"}

            # Wait for response
            try:
                return response_queue.get(timeout=timeout)
            except queue.Empty:
                return {"error": "Timeout waiting for response", "status": "timeout"}
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def deliver_response(self, message: dict[str, Any]) -> bool:
        """Deliver a response to a waiting request.

        Called by the pipe reader when a response arrives.

        Args:
            message: Response message from DLL

        Returns:
            True if delivered to a waiting request, False otherwise
        """
        request_id = message.get("request_id")
        if not request_id:
            return False

        with self._pending_lock:
            response_queue = self._pending.get(request_id)
            if response_queue:
                response_queue.put(message)
                return True
        return False

    def _write(self, data: bytes) -> bool:
        """Write data to pipe."""
        bytes_written = wintypes.DWORD(0)
        ok = WinAPI.WriteFile(
            self._handle, data, len(data), ctypes.byref(bytes_written), None
        )
        if not ok or bytes_written.value != len(data):
            return False
        WinAPI.FlushFileBuffers(self._handle)
        return True


class NamedPipeServer:
    """Named pipe server for DLL communication.

    Manages:
    - Pipe lifecycle (create, connect, disconnect)
    - Message reading and routing
    - Game state updates
    - Logging
    """

    def __init__(self, pipe_name: str, game_state: Optional["GameState"] = None):
        """Initialize the pipe server.

        Args:
            pipe_name: Full pipe path (e.g., r"\\\\.\\pipe\\civv_llm")
            game_state: GameState instance to update from messages
        """
        if not pipe_name.startswith("\\\\.\\pipe\\"):
            raise ValueError("pipe_name must start with \\\\.\\pipe\\")

        self.pipe_name = pipe_name
        self._game_state = game_state
        self._running = False
        self._handle: Optional[int] = None
        self._pipe_conn: Optional[PipeConnection] = None
        self._connection_ready = threading.Event()

        # Message processing queue and worker
        self._message_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None

        # Validation state (for detecting issues)
        self._last_turn: Optional[int] = None
        self._last_game_id: Optional[int] = None

        # Connect logger to game state
        if game_state:
            get_message_logger().set_game_state(game_state)

    def start(self) -> None:
        """Start the pipe server (blocking)."""
        if self._running:
            return
        self._running = True
        self._start_worker()
        self._serve_loop()

    def stop(self) -> None:
        """Stop the pipe server."""
        self._running = False
        if self._handle:
            try:
                WinAPI.CancelIoEx(self._handle, None)
            except Exception:
                pass
        self._close()

    def get_pipe_connection(self, timeout: Optional[float] = None) -> Optional[PipeConnection]:
        """Wait for pipe connection to be established.

        Args:
            timeout: Max seconds to wait. None = wait forever, 0 = don't wait.

        Returns:
            PipeConnection if connected, None if timeout
        """
        if timeout == 0:
            return self._pipe_conn if self._connection_ready.is_set() else None
        if self._connection_ready.wait(timeout=timeout):
            return self._pipe_conn
        return None

    def send_request(self, request: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        """Send a request to the DLL (convenience method).

        Args:
            request: Request dict
            timeout: Seconds to wait for response

        Returns:
            Response dict from DLL

        Raises:
            RuntimeError: If no pipe connection
        """
        conn = self.get_pipe_connection(timeout=0)
        if not conn:
            raise RuntimeError("No pipe connection available")
        return conn.send_request(request, timeout=timeout)

    # --- Internal methods ---

    def _start_worker(self) -> None:
        """Start the message processing worker thread."""
        def worker():
            while self._running:
                try:
                    message = self._message_queue.get(timeout=0.1)
                    self._process_message(message)
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        self._worker_thread = threading.Thread(target=worker, daemon=True, name="MsgWorker")
        self._worker_thread.start()

    def _process_message(self, message: dict[str, Any]) -> None:
        """Process an incoming DLL message.

        - Logs to JSONL (except heartbeats)
        - Updates GameState
        - Validates for anomalies
        """
        msg_type = message.get("type", "unknown")

        # Log everything except heartbeats
        if msg_type != "heartbeat":
            get_message_logger().log(message, direction="incoming")

        # Update game state
        if msg_type in ("turn_start", "heartbeat") and self._game_state:
            self._game_state.update_from_message(message)

        # Validate turn_start messages
        if msg_type == "turn_start":
            self._validate_turn(message)

    def _validate_turn(self, message: dict[str, Any]) -> None:
        """Check for turn rewind or game_id change (warns only)."""
        new_turn = message.get("turn")
        new_game_id = message.get("game_id")

        # Check for turn rewind
        if self._last_turn is not None and new_turn is not None:
            if new_turn < self._last_turn:
                logger.warning(f"Turn rewind detected: {self._last_turn} → {new_turn}")

        # Check for game ID change (indicates new game)
        if self._last_game_id is not None and new_game_id is not None:
            if new_game_id != self._last_game_id:
                logger.info(f"Game ID changed: {self._last_game_id} → {new_game_id} (new game?)")
                # Reset game state on new game
                if self._game_state:
                    self._game_state.reset()

        self._last_turn = new_turn
        self._last_game_id = new_game_id

    def _serve_loop(self) -> None:
        """Main server loop: create pipe, wait for client, handle messages."""
        while self._running:
            try:
                h = self._create_pipe()
                logger.info(f"Pipe created: {self.pipe_name}")

                # Wait for client connection
                ok = WinAPI.ConnectNamedPipe(h, None)
                if not ok:
                    err = ctypes.get_last_error()
                    if err != WinAPI.ERROR_PIPE_CONNECTED:
                        logger.error(f"ConnectNamedPipe failed: {err}")
                        self._close()
                        continue

                # Set message mode
                mode = wintypes.DWORD(WinAPI.PIPE_READMODE_MESSAGE)
                WinAPI.SetNamedPipeHandleState(h, ctypes.byref(mode), None, None)

                logger.info("DLL connected")
                self._client_loop(h)

            except Exception as e:
                logger.error(f"Pipe server error: {e}")
            finally:
                self._close()

    def _create_pipe(self) -> int:
        """Create the named pipe."""
        h = WinAPI.CreateNamedPipeW(
            self.pipe_name,
            WinAPI.PIPE_ACCESS_DUPLEX,
            WinAPI.PIPE_TYPE_MESSAGE | WinAPI.PIPE_READMODE_MESSAGE | WinAPI.PIPE_WAIT,
            1,  # max instances
            WinAPI.BUFSIZE,
            WinAPI.BUFSIZE,
            0,
            None,
        )
        if h == WinAPI.INVALID_HANDLE_VALUE or h == 0:
            err = ctypes.get_last_error()
            raise OSError(err, f"CreateNamedPipeW failed: {err}")
        self._handle = h
        return h

    def _close(self) -> None:
        """Close the pipe and reset state."""
        h = self._handle
        self._handle = None
        self._pipe_conn = None
        self._connection_ready.clear()

        if h:
            try:
                WinAPI.FlushFileBuffers(h)
            except Exception:
                pass
            try:
                WinAPI.DisconnectNamedPipe(h)
            except Exception:
                pass
            try:
                WinAPI.CloseHandle(h)
            except Exception:
                pass

    def _client_loop(self, h: int) -> None:
        """Handle messages from a connected client."""
        self._pipe_conn = PipeConnection(h)
        self._connection_ready.set()

        buf = (ctypes.c_char * WinAPI.BUFSIZE)()
        bytes_read = wintypes.DWORD(0)
        bytes_avail = wintypes.DWORD(0)

        while self._running:
            # Non-blocking peek
            if not WinAPI.PeekNamedPipe(h, None, 0, None, ctypes.byref(bytes_avail), None):
                break

            if bytes_avail.value == 0:
                time.sleep(0.01)  # 10ms polling
                continue

            # Read available data
            ok = WinAPI.ReadFile(h, buf, WinAPI.BUFSIZE, ctypes.byref(bytes_read), None)
            if not ok:
                err = ctypes.get_last_error()
                if err == WinAPI.ERROR_MORE_DATA:
                    # Partial read, process what we have
                    self._dispatch(bytes(buf[: bytes_read.value]))
                    continue
                break

            if bytes_read.value == 0:
                break

            self._dispatch(bytes(buf[: bytes_read.value]))

        logger.info("DLL disconnected")

    def _dispatch(self, data: bytes) -> None:
        """Parse and route incoming messages.

        - Responses (with request_id) → deliver to waiting request
        - Events → queue for worker thread
        """
        for line in data.split(b"\n"):
            line = line.strip()
            if not line:
                continue

            try:
                message = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to parse message: {e}")
                continue

            # Try to deliver as response to pending request
            if self._pipe_conn and self._pipe_conn.deliver_response(message):
                continue

            # Queue for processing
            self._message_queue.put(message)
