from __future__ import annotations

import ctypes
import json
import logging
import queue
import threading
import uuid
from ctypes import wintypes
from typing import Any, Callable, Optional

from .message_validator import MessageValidator


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
    """

    def __init__(self, handle: int):
        self._handle = handle
        self._lock = threading.Lock()
        self._log = logging.getLogger(__name__)
        self._buf = (ctypes.c_char * WinAPI.BUFSIZE)()
        # Response waiting mechanism for synchronous requests
        self._pending_responses: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._response_lock = threading.Lock()

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Send an action to the DLL (fire-and-forget, non-blocking).

        Thread-safe: can be called from HTTP handler thread.
        Never waits for response - we can't trust DLL responses.
        """
        with self._lock:
            self._log.info(f"📤 Outgoing to DLL: action: {action}")
            
            message = json.dumps(action).encode("utf-8") + b"\n"
            if not self._write(message):
                self._log.error("Failed to write action to pipe")
                return {"error": "Pipe write failed", "status": "sent", "action": action}
            
            # Fire-and-forget - return immediately
            return {"status": "sent", "action": action}

    def send_end_turn(self) -> None:
        """Send end_turn signal to DLL (no response expected)."""
        with self._lock:
            msg = {"type": "end_turn"}
            self._log.info(f"📤 Outgoing to DLL: end_turn: {msg}")
            message = json.dumps(msg).encode("utf-8") + b"\n"
            self._write(message)  # Fire and forget - don't block on errors

    def send_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send a request to the DLL (fire-and-forget, non-blocking).
        
        Thread-safe: can be called from HTTP handler thread.
        Never waits for response - we can't trust DLL responses.
        
        Args:
            request: Request dictionary (must have 'type' field)
            
        Returns:
            Status dict indicating request was sent
        """
        with self._lock:
            self._log.info(f"📤 Outgoing to DLL: request: {request}")
            
            message = json.dumps(request).encode("utf-8") + b"\n"
            if not self._write(message):
                self._log.error("Failed to write request to pipe")
                return {"error": "Pipe write failed", "status": "sent", "request": request}
            
            # Fire-and-forget - return immediately
            return {"status": "sent", "request": request}
    
    def deliver_response(self, response: dict[str, Any]) -> bool:
        """Deliver a response to a waiting request.
        
        Called by StateProcessor when it receives a response message.
        
        Args:
            response: Response dictionary (must have 'request_id' field)
            
        Returns:
            True if response was delivered to a waiting request, False otherwise
        """
        request_id = response.get("request_id")
        if not request_id:
            return False
        
        with self._response_lock:
            response_queue = self._pending_responses.get(request_id)
            if response_queue:
                response_queue.put(response)
                return True
        
        return False

    def _write(self, data: bytes) -> bool:
        bytes_written = wintypes.DWORD(0)
        ok = WinAPI.WriteFile(self._handle, data, len(data), ctypes.byref(bytes_written), None)
        if not ok or bytes_written.value != len(data):
            err = ctypes.get_last_error()
            self._log.error(f"Pipe write failed: {err}")
            return False
        return True

    def _read(self) -> Optional[bytes]:
        bytes_read = wintypes.DWORD(0)
        ok = WinAPI.ReadFile(self._handle, self._buf, WinAPI.BUFSIZE, ctypes.byref(bytes_read), None)
        if not ok:
            err = ctypes.get_last_error()
            if err != WinAPI.ERROR_MORE_DATA:
                self._log.error(f"Pipe read failed: {err}")
                return None
        if bytes_read.value == 0:
            return None
        return bytes(self._buf[:bytes_read.value])


# Callback type: receives state dict and pipe connection for sending actions
OnTurnStart = Callable[[dict[str, Any], PipeConnection], None]


class StateProcessor:
    """Processes incoming state messages with validation and persistence."""
    
    def __init__(self):
        """Initialize state processor."""
        self.validator = MessageValidator()
        self._last_state: Optional[dict[str, Any]] = None
        self._log = logging.getLogger(__name__)
    
    def process_state(
        self,
        state: dict[str, Any],
        on_turn_start: OnTurnStart,
        pipe_conn: PipeConnection
    ) -> None:
        """Process an incoming state message.
        
        Args:
            state: State dictionary from DLL
            on_turn_start: Callback to handle turn start
            pipe_conn: Pipe connection for this turn
        """
        msg_type = state.get("type", "unknown")
        
        # Handle response messages (player_status_result, units_result, action_result, etc.)
        # These need to be delivered to waiting requests
        if msg_type in ("player_status_result", "units_result", "action_result") or msg_type.endswith("_result"):
            if pipe_conn.deliver_response(state):
                # Response was delivered to a waiting request
                return
            # If no waiting request, log and skip (response messages aren't state updates)
            self._log.debug(f"Received {msg_type} response with no waiting request")
            return
        
        # Handle error responses
        if msg_type == "error" and "request_id" in state:
            if pipe_conn.deliver_response(state):
                # Error response was delivered to a waiting request
                return
            # If no waiting request, log and skip
            self._log.debug(f"Received error response with no waiting request: {state.get('message')}")
            return
        
        # Log EVERYTHING from DLL to JSONL file
        # Import here to avoid circular dependency
        from .game_logger import GameLogger
        
        # Get or create game logger (simple singleton pattern)
        if not hasattr(self, "_message_logger"):
            self._message_logger = GameLogger()
        
        # Just push everything we get from DLL
        self._message_logger.log_message(state)
        
        # Handle game notifications from DLL (still return early, don't process as state)
        if msg_type == "game_notification" or msg_type == "notification":
            return  # Don't process as a state message
        
        # Validate message
        is_valid, error_msg = self.validator.validate_message(state)
        
        if not is_valid:
            self._log.error(f"Message validation failed: {error_msg}")
            return
        
        # Check consistency with previous turn_start message
        if self._last_state:
            is_consistent, warning = self.validator.check_turn_consistency(self._last_state, state)
            if not is_consistent:
                self._log.warning(f"Turn consistency issue: {warning}")
        
        # Update last state
        self._last_state = state
        
        # Call the turn start handler
        if msg_type == "turn_start":
            on_turn_start(state, pipe_conn)


class NamedPipeServer:
    """Single-client named-pipe server for turn-based communication.

    When DLL sends a turn_start message:
    1. Parses the state
    2. Calls on_turn_start(state, pipe_connection) in a separate thread
    3. Handler can use pipe_connection to send actions and receive responses
    4. Pipe reading continues immediately, allowing new messages to be processed
    """

    def __init__(
        self,
        pipe_name: str,
        on_turn_start: OnTurnStart
    ):
        if not pipe_name.startswith("\\\\.\\pipe\\"):
            raise ValueError("pipe_name must start with \\\\.\\pipe\\")
        self.pipe_name = pipe_name
        self.on_turn_start = on_turn_start
        self._running = False
        self._log = logging.getLogger(__name__)
        self._handle: Optional[int] = None
        self._current_handler_thread: Optional[threading.Thread] = None
        self._handler_lock = threading.Lock()
        
        # State processing
        self.state_processor = StateProcessor()

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
                self._log.info(f"Waiting for client on {self.pipe_name}...")
                ok = WinAPI.ConnectNamedPipe(h, None)
                if not ok:
                    err = ctypes.get_last_error()
                    if err != WinAPI.ERROR_PIPE_CONNECTED:
                        self._log.error(f"ConnectNamedPipe failed: {err}")
                        self._close()
                        continue
                mode = wintypes.DWORD(WinAPI.PIPE_READMODE_MESSAGE)
                WinAPI.SetNamedPipeHandleState(h, ctypes.byref(mode), None, None)
                self._log.info("Client connected")

                self._client_loop(h)
            finally:
                self._close()

    def _client_loop(self, h: int) -> None:
        buf = (ctypes.c_char * WinAPI.BUFSIZE)()
        bytes_read = wintypes.DWORD(0)
        pipe_conn = PipeConnection(h)

        while self._running:
            # Wait for message from DLL (turn_start)
            ok = WinAPI.ReadFile(h, buf, WinAPI.BUFSIZE, ctypes.byref(bytes_read), None)
            if not ok:
                err = ctypes.get_last_error()
                if err == WinAPI.ERROR_MORE_DATA:
                    chunk = bytes(buf[:bytes_read.value])
                    self._dispatch(chunk, pipe_conn)
                    continue
                self._log.info(f"Client disconnected or read error: {err}")
                break
            if bytes_read.value == 0:
                self._log.info("Client closed pipe")
                break

            data = bytes(buf[:bytes_read.value])
            self._dispatch(data, pipe_conn)

    def _dispatch(self, data: bytes, pipe_conn: PipeConnection) -> None:
        """Dispatch message to handler thread immediately.
        
        Returns as fast as possible to allow next ReadFile to start.
        All parsing and processing happens in the handler thread.
        """
        # Run handler in separate thread so pipe reading can continue immediately
        # This ensures we never miss messages - next ReadFile starts right away
        def run_handler():
            try:
                # Parse JSON (moved here to keep _dispatch fast)
                try:
                    decoded = data.decode("utf-8").rstrip("\r\n")
                    state = json.loads(decoded)
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    self._log.error(f"Failed to parse message: {e}, raw data: {data[:100]!r}")
                    return

                # Log incoming message from DLL
                msg_type = state.get("type", "unknown") if isinstance(state, dict) else "non-dict"
                self._log.info(f"📥 Incoming from DLL: {msg_type}: {state}")

                # Process state (validation, persistence, notifications)
                self.state_processor.process_state(state, self.on_turn_start, pipe_conn)
            except Exception as e:
                self._log.error(f"Handler error: {e}", exc_info=True)
            finally:
                # Clear handler thread reference when done
                with self._handler_lock:
                    if self._current_handler_thread == threading.current_thread():
                        self._current_handler_thread = None

        # Use a placeholder name - we'll update it in the handler if parsing succeeds
        handler_thread = threading.Thread(target=run_handler, daemon=True, name="TurnHandler-pending")
        with self._handler_lock:
            self._current_handler_thread = handler_thread
        handler_thread.start()
