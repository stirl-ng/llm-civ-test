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
    from .event_broadcaster import EventBroadcaster

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

    def __init__(
        self,
        pipe_name: str,
        broadcaster: Optional["EventBroadcaster"] = None,
    ):
        """Initialize the pipe server.

        Args:
            pipe_name: Full pipe path (e.g., r"\\\\.\\pipe\\civv_llm")
            broadcaster: Optional EventBroadcaster for SSE push events.
        """
        if not pipe_name.startswith("\\\\.\\pipe\\"):
            raise ValueError("pipe_name must start with \\\\.\\pipe\\")

        self.pipe_name = pipe_name
        self._broadcaster = broadcaster

        # Game metadata — updated from DLL messages
        self._state_lock = threading.Lock()
        self._turn_number: Optional[int] = None
        self._game_id: Optional[int] = None
        self._player_id: Optional[int] = None
        self._player_name: Optional[str] = None
        self._connected: bool = False

        get_message_logger().set_pipe_server(self)
        self._running = False
        self._handle: Optional[int] = None
        self._pipe_conn: Optional[PipeConnection] = None
        self._connection_ready = threading.Event()

        # Message processing queue and worker
        self._message_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None

    # --- Game state (metadata from DLL messages) ---

    def _update_state(self, message: dict[str, Any]) -> None:
        """Update game metadata from a DLL message."""
        with self._state_lock:
            if not self._connected:
                self._connected = True
                logger.info("Game connection established")
            if "turn" in message:
                new_turn = message["turn"]
                if self._turn_number != new_turn:
                    logger.debug(f"Turn: {self._turn_number} → {new_turn}")
                    # Warn on rewind
                    if self._turn_number is not None and new_turn < self._turn_number:
                        logger.warning(f"Turn rewind detected: {self._turn_number} → {new_turn}")
                    self._turn_number = new_turn
            if "game_id" in message:
                new_game_id = message["game_id"]
                if self._game_id != new_game_id:
                    if self._game_id is not None:
                        logger.info(f"Game ID changed: {self._game_id} → {new_game_id} (new game?)")
                        self._reset_state_locked()
                    else:
                        logger.debug(f"Game ID: {self._game_id} → {new_game_id}")
                    self._game_id = new_game_id
            if "player_id" in message:
                new_player_id = message["player_id"]
                if self._player_id != new_player_id:
                    logger.debug(f"Player ID: {self._player_id} → {new_player_id}")
                    self._player_id = new_player_id
            if "player_name" in message:
                new_player_name = message["player_name"]
                if self._player_name != new_player_name:
                    logger.debug(f"Player: {self._player_name} → {new_player_name}")
                    self._player_name = new_player_name

    def _reset_state_locked(self) -> None:
        """Reset state fields — must be called with _state_lock held."""
        self._turn_number = None
        self._game_id = None
        self._player_id = None
        self._player_name = None
        self._connected = False
        logger.info("Game state reset")

    def _reset_state(self) -> None:
        """Reset state (on disconnect or new game)."""
        with self._state_lock:
            self._reset_state_locked()

    def get_metadata(self) -> dict[str, Any]:
        """Return current game metadata."""
        with self._state_lock:
            return {
                "turn_number": self._turn_number,
                "game_id": self._game_id,
                "player_id": self._player_id,
                "player_name": self._player_name,
                "connected": self._connected,
            }

    @property
    def turn_number(self) -> Optional[int]:
        with self._state_lock:
            return self._turn_number

    @property
    def game_id(self) -> Optional[int]:
        with self._state_lock:
            return self._game_id

    @property
    def player_id(self) -> Optional[int]:
        with self._state_lock:
            return self._player_id

    # --- Lifecycle ---

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
        - Updates game metadata
        """
        msg_type = message.get("type", "unknown")

        # Log everything except heartbeats
        if msg_type != "heartbeat":
            get_message_logger().log(message, direction="incoming")

        # Update game metadata from DLL messages
        if msg_type in ("turn_start", "heartbeat"):
            self._update_state(message)

        # Emit turn_start event to SSE subscribers
        if msg_type == "turn_start" and self._broadcaster:
            self._broadcaster.emit("turn_start", {
                "turn":        message.get("turn"),
                "game_id":     message.get("game_id"),
                "player_id":   message.get("player_id"),
                "player_name": message.get("player_name"),
            })

        elif msg_type == "turn_complete" and self._broadcaster:
            self._broadcaster.emit("turn_complete", {
                "turn":        message.get("turn"),
                "game_id":     message.get("game_id"),
                "player_id":   message.get("player_id"),
                "player_name": message.get("player_name"),
            })

        # Reconnect recovery: DLL doesn't resend turn_start on pipe reconnect,
        # so synthesize one from the first heartbeat if no turn is pending.
        elif msg_type == "heartbeat" and self._broadcaster and not self._broadcaster.has_pending_turn():
            logger.info("Synthesizing turn_start from heartbeat (reconnect recovery)")
            self._broadcaster.emit("turn_start", {
                "turn":        message.get("turn"),
                "game_id":     message.get("game_id"),
                "player_id":   message.get("player_id"),
                "player_name": message.get("player_name"),
            })

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

        self._reset_state()

        # Notify SSE subscribers that DLL disconnected
        if self._broadcaster:
            self._broadcaster.emit("disconnected", {})

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

            # Sync turn/game state from every DLL message, including responses.
            self._update_state(message)

            # Try to deliver as response to pending request
            if self._pipe_conn and self._pipe_conn.deliver_response(message):
                continue

            # Queue for processing
            self._message_queue.put(message)
