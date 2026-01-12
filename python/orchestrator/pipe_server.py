from __future__ import annotations

import ctypes
import json
import queue
import threading
import time
import uuid
from ctypes import wintypes
from typing import TYPE_CHECKING, Any, Optional

from .message_validator import MessageValidator

if TYPE_CHECKING:
    from .mcp_server import CivMCPServer


LPSECURITY_ATTRIBUTES = ctypes.c_void_p


class WinAPI:
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
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        LPSECURITY_ATTRIBUTES,
    ]
    CreateNamedPipeW.restype = wintypes.HANDLE

    ConnectNamedPipe = kernel32.ConnectNamedPipe
    ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    ConnectNamedPipe.restype = wintypes.BOOL

    SetNamedPipeHandleState = kernel32.SetNamedPipeHandleState
    SetNamedPipeHandleState.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p]
    SetNamedPipeHandleState.restype = wintypes.BOOL

    ReadFile = kernel32.ReadFile
    ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    ReadFile.restype = wintypes.BOOL

    WriteFile = kernel32.WriteFile
    WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    WriteFile.restype = wintypes.BOOL

    FlushFileBuffers = kernel32.FlushFileBuffers
    FlushFileBuffers.argtypes = [wintypes.HANDLE]
    FlushFileBuffers.restype = wintypes.BOOL

    PeekNamedPipe = kernel32.PeekNamedPipe
    PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
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
    """Thread-safe wrapper for pipe I/O during a turn.

    Allows the HTTP thread to send actions and receive responses
    while the pipe thread waits.

    NOTE: Multiplayer considerations
    =================================
    Currently designed for single-client use. The request_id-based response
    routing works for one client, but for simultaneous multiplayer we'd need:
    1. Client/session identification in request_id or separate routing mechanism
    2. Per-client response queues to prevent cross-client response delivery
    3. Consider async architecture if multiple clients need concurrent access
    """

    def __init__(self, handle: int):
        self._handle = handle
        self._lock = threading.Lock()
        self._buf = (ctypes.c_char * WinAPI.BUFSIZE)()
        # Response waiting mechanism for synchronous requests
        self._pending_responses: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._response_lock = threading.Lock()

    def send_request(self, request: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        """Send a request to the DLL and wait for response.
        
        Thread-safe: can be called from HTTP handler thread.
        
        Args:
            request: Request dictionary (must have 'type' field)
            timeout: Seconds to wait for response
            
        Returns:
            Status dict indicating request was sent
        """
        request_id = request.get("request_id") or str(uuid.uuid4())
        request["request_id"] = request_id
        
        q = queue.Queue()
        with self._response_lock:
            self._pending_responses[request_id] = q
            
        try:
            with self._lock:
                message = json.dumps(request).encode("utf-8") + b"\n"
                if not self._write(message):
                    return {"error": "Pipe write failed", "status": "failed", "request": request}
            
            try:
                response = q.get(timeout=timeout)
                return response
            except queue.Empty:
                return {"error": "Timeout waiting for response", "status": "timeout", "request": request}
        finally:
            with self._response_lock:
                self._pending_responses.pop(request_id, None)
    
    def acknowledge_response(self, response: dict[str, Any]) -> bool:
        """Deliver a response to a waiting request.
        
        Called by StateProcessor when it receives a response message.
        
        Args:
            response: Response dictionary (must have 'request_id' field)
            
        Returns:
            True if response was delivered to a waiting request, False otherwise
        """
        request_id = response.get("request_id")
        msg_type = response.get("type")
        delivered = False
        
        with self._response_lock:
            # 1. Try to deliver by request_id
            if request_id:
                response_queue = self._pending_responses.get(request_id)
                if response_queue:
                    response_queue.put(response)
                    delivered = True
            
            # 2. Try to deliver by message type if not delivered (fallback for end_turn_result)
            if not delivered and msg_type:
                response_queue = self._pending_responses.get(msg_type)
                if response_queue:
                    response_queue.put(response)
                    delivered = True
        
        return delivered

    def _write(self, data: bytes) -> bool:
        bytes_written = wintypes.DWORD(0)
        ok = WinAPI.WriteFile(self._handle, data, len(data), ctypes.byref(bytes_written), None)
        if not ok or bytes_written.value != len(data):
            return False
        # Flush to ensure data is actually transmitted to the client
        WinAPI.FlushFileBuffers(self._handle)
        return True

    def _read(self) -> Optional[bytes]:
        bytes_read = wintypes.DWORD(0)
        ok = WinAPI.ReadFile(self._handle, self._buf, WinAPI.BUFSIZE, ctypes.byref(bytes_read), None)
        if not ok:
            err = ctypes.get_last_error()
            if err != WinAPI.ERROR_MORE_DATA:
                return None
        if bytes_read.value == 0:
            return None
        return bytes(self._buf[:bytes_read.value])


class StateProcessor:
    """Processes incoming messages from DLL - validates, logs, and routes to CivMCPServer."""

    def __init__(self, mcp_server: Optional["CivMCPServer"] = None):
        """Initialize state processor.

        Args:
            mcp_server: CivMCPServer instance for turn management (holds all state)
        """
        self.validator = MessageValidator()
        self._last_state: Optional[dict[str, Any]] = None
        self.mcp_server = mcp_server

    def process_message(self, message: dict[str, Any]) -> None:
        """Process an incoming message from DLL.

        Routes responses to waiting requests, logs everything, validates,
        and calls mcp_server on turn events.

        Args:
            message: Message dictionary from DLL
        """
        # Log EVERYTHING from DLL to JSONL file (before any early returns)
        from .game_logger import get_game_logger
        log_msg = message.copy()
        log_msg["direction"] = "incoming"
        get_game_logger().log_message(log_msg)

        msg_type = message.get("type", "unknown")

        # Route turn events to mcp_server
        if msg_type == "turn_start" and self.mcp_server:
            self.mcp_server.start_turn(message)
        elif msg_type == "heartbeat" and self.mcp_server:
            self.mcp_server.handle_heartbeat(message)

        # Notifications and trace don't need further processing
        if msg_type in ("game_notification", "notification", "trace"):
            return

        # Handle response messages - deliver to waiting requests
        if self.mcp_server and self.mcp_server.acknowledge_response(message):
            return

        # Validate message
        is_valid, error_msg = self.validator.validate_message(message)
        if not is_valid:
            return

        # Check consistency with previous turn_start
        if self._last_state:
            is_consistent, warning = self.validator.check_turn_consistency(self._last_state, message)

        self._last_state = message



class NamedPipeServer:
    """Single-client named-pipe server for turn-based communication.

    When DLL sends a turn_start message:
    1. Parses the state
    2. Handler can use pipe_connection to send actions and receive responses
    3. Pipe reading continues immediately, allowing new messages to be processed
    """

    def __init__(
        self,
        pipe_name: str,
        mcp_server: Optional["CivMCPServer"] = None
    ):
        if not pipe_name.startswith("\\\\.\\pipe\\"):
            raise ValueError("pipe_name must start with \\\\.\\pipe\\")
        self.pipe_name = pipe_name
        self.mcp_server = mcp_server
        self._running = False
        self._handle: Optional[int] = None
        self._current_handler_thread: Optional[threading.Thread] = None
        self._handler_lock = threading.Lock()

        # State processing - pass mcp_server for turn management
        self.state_processor = StateProcessor(mcp_server=mcp_server)
        
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._serve_loop()

    def stop(self) -> None:
        self._running = False
        if self._handle:
            try:
                WinAPI.CancelIoEx(self._handle, None)
            except Exception:
                pass
        self._close()

    def _create(self) -> int:
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
        h = self._handle
        self._handle = None
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

    def _serve_loop(self) -> None:
        while self._running:
            try:
                h = self._create()
                ok = WinAPI.ConnectNamedPipe(h, None)
                if not ok:
                    err = ctypes.get_last_error()
                    if err != WinAPI.ERROR_PIPE_CONNECTED:
                        self._close()
                        continue
                mode = wintypes.DWORD(WinAPI.PIPE_READMODE_MESSAGE)
                WinAPI.SetNamedPipeHandleState(h, ctypes.byref(mode), None, None)

                self._client_loop(h)
            finally:
                self._close()

    def _client_loop(self, h: int) -> None:
        buf = (ctypes.c_char * WinAPI.BUFSIZE)()
        bytes_read = wintypes.DWORD(0)
        bytes_avail = wintypes.DWORD(0)
        pipe_conn = PipeConnection(h)

        # Set pipe connection on mcp_server once at connection time
        if self.mcp_server:
            self.mcp_server.set_pipe_connection(pipe_conn)

        while self._running:
            # Non-blocking peek to check if data is available
            # This allows writes from other threads to proceed without blocking
            if not WinAPI.PeekNamedPipe(h, None, 0, None, ctypes.byref(bytes_avail), None):
                break

            if bytes_avail.value == 0:
                # No data available, sleep briefly and try again
                # This keeps the loop responsive to writes from HTTP thread
                time.sleep(0.01)  # 10ms polling interval
                continue

            # Data available, now read it
            ok = WinAPI.ReadFile(h, buf, WinAPI.BUFSIZE, ctypes.byref(bytes_read), None)
            if not ok:
                err = ctypes.get_last_error()
                if err == WinAPI.ERROR_MORE_DATA:
                    chunk = bytes(buf[:bytes_read.value])
                    self._dispatch(chunk)
                    continue
                break
            if bytes_read.value == 0:
                break

            data = bytes(buf[:bytes_read.value])
            self._dispatch(data)

    def _dispatch(self, data: bytes) -> None:
        """Dispatch message(s) to handler thread immediately.

        Handles newline-delimited JSON, potentially multiple messages in one chunk.
        Returns as fast as possible to allow next ReadFile to start.
        """
        def run_handler_pool():
            # Split data by newlines in case multiple messages arrived together
            messages = data.split(b"\n")
            for msg in messages:
                try:
                    decoded = msg.decode("utf-8").strip()
                    if not decoded or not decoded.strip():
                        continue
                    message = json.loads(decoded)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    from .game_logger import get_game_logger
                    get_game_logger().log_message({"error": "Failed to decode message", "message": msg})
                    continue
                # Process state (validation, persistence, notifications, and delivery to waiting sync requests)
                self.state_processor.process_message(message)

            # Cleanup thread reference
            with self._handler_lock:
                if self._current_handler_thread == threading.current_thread():
                    self._current_handler_thread = None

        # Run handler in separate thread so pipe reading can continue immediately
        handler_thread = threading.Thread(target=run_handler_pool, daemon=True, name="MsgHandler")
        with self._handler_lock:
            self._current_handler_thread = handler_thread
        handler_thread.start()
