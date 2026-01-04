from __future__ import annotations

import ctypes
import json
import threading
from ctypes import wintypes
from typing import Any, Callable, Optional

from .logging_setup import get_logger
from .state_db import StateDatabase
from .state_validator import StateValidator
from .notification_handler import NotificationHandler


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
        self._log = get_logger()
        self._buf = (ctypes.c_char * WinAPI.BUFSIZE)()

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Send an action to the DLL and wait for response.

        Thread-safe: can be called from HTTP handler thread.
        """
        with self._lock:
            # Send action
            action_type = action.get("type", "unknown")
            action_kind = action.get("action", {}).get("kind", "unknown") if isinstance(action.get("action"), dict) else "unknown"
            self._log.info(f"Sending action to DLL: type={action_type}, kind={action_kind}")
            
            message = json.dumps(action).encode("utf-8")
            self._write(message)

            # Read response
            response_data = self._read()
            if response_data is None:
                self._log.error("Failed to read response from DLL")
                return {"error": "Pipe read failed"}

            # Log raw response receipt
            self._log.info(f"Received response from DLL: {len(response_data)} bytes")

            try:
                response = json.loads(response_data.decode("utf-8"))
                # Log parsed response details
                resp_type = response.get("type", "unknown") if isinstance(response, dict) else "non-dict"
                resp_info = f"type={resp_type}"
                if isinstance(response, dict):
                    if "request_id" in response:
                        resp_info += f", request_id={response['request_id']}"
                    if "success" in response:
                        resp_info += f", success={response['success']}"
                self._log.info(f"Parsed response from DLL: {resp_info}")
                return response
            except json.JSONDecodeError as e:
                self._log.error(f"Invalid JSON response: {e}, raw data: {response_data[:100]!r}")
                return {"error": f"Invalid JSON response: {e}"}

    def send_end_turn(self) -> None:
        """Send end_turn signal to DLL (no response expected)."""
        with self._lock:
            self._log.info("Sending end_turn signal to DLL")
            message = json.dumps({"type": "end_turn"}).encode("utf-8")
            self._write(message)

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
    """Processes incoming state messages with validation, persistence, and notifications."""
    
    def __init__(
        self,
        state_db: Optional[StateDatabase] = None,
        notification_handler: Optional[NotificationHandler] = None
    ):
        """Initialize state processor.
        
        Args:
            state_db: Optional database for persistence
            notification_handler: Optional notification handler
        """
        self.state_db = state_db
        self.notification_handler = notification_handler
        self.validator = StateValidator()
        self._last_state: Optional[dict[str, Any]] = None
        self._log = get_logger()
    
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
        # Validate state
        is_valid, error_msg = self.validator.validate_state(state)
        
        if not is_valid:
            self._log.error(f"State validation failed: {error_msg}")
            if self.notification_handler:
                self.notification_handler.notify_validation_error(error_msg, state)
            if self.state_db:
                self.state_db.save_state(state, validated=False, validation_errors=error_msg)
            return
        
        # Check consistency with previous state
        if self._last_state:
            is_consistent, warning = self.validator.check_state_consistency(self._last_state, state)
            if not is_consistent:
                self._log.warning(f"State consistency issue: {warning}")
                if self.notification_handler:
                    self.notification_handler.notify_consistency_warning(
                        warning or "Unknown consistency issue",
                        self._last_state.get("turn"),
                        state.get("turn")
                    )
        
        # Save to database
        if self.state_db:
            self.state_db.save_state(state, validated=True)
        
        # Send notifications
        msg_type = state.get("type", "unknown")
        turn = state.get("turn")
        
        if self.notification_handler:
            self.notification_handler.notify_state_received(msg_type, turn)
            
            if msg_type == "turn_start":
                player_id = state.get("player_id")
                if player_id is not None and turn is not None:
                    self.notification_handler.notify_turn_start(turn, player_id, state)
        
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
        on_turn_start: OnTurnStart,
        state_db: Optional[StateDatabase] = None,
        notification_handler: Optional[NotificationHandler] = None
    ):
        if not pipe_name.startswith("\\\\.\\pipe\\"):
            raise ValueError("pipe_name must start with \\\\.\\pipe\\")
        self.pipe_name = pipe_name
        self.on_turn_start = on_turn_start
        self._running = False
        self._log = get_logger()
        self._handle: Optional[int] = None
        self._current_handler_thread: Optional[threading.Thread] = None
        self._handler_lock = threading.Lock()
        
        # State processing
        self.state_processor = StateProcessor(state_db, notification_handler)

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
        # Log raw message receipt
        # self._log.info(f"Received message from DLL: {len(data)} bytes")
        
        try:
            decoded = data.decode("utf-8").rstrip("\r\n")
            state = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._log.error(f"Failed to parse message: {e}, raw data: {data[:100]!r}")
            if self.state_processor.notification_handler:
                self.state_processor.notification_handler.notify_pipe_error(f"Parse error: {e}")
            return

        # Log parsed message details
        msg_type = state.get("type", "unknown") if isinstance(state, dict) else "non-dict"
        msg_info = f"type={msg_type}"
        if isinstance(state, dict):
            if "turn" in state:
                msg_info += f", turn={state['turn']}"
            if "player_id" in state:
                msg_info += f", player_id={state['player_id']}"
        self._log.info(f"Parsed message from DLL: {msg_info}")

        # Run handler in separate thread so pipe reading can continue
        # This allows new messages to be processed even if handler is blocking
        def run_handler():
            try:
                # Process state (validation, persistence, notifications)
                self.state_processor.process_state(state, self.on_turn_start, pipe_conn)
            except Exception as e:
                self._log.error(f"Handler error: {e}", exc_info=True)
                if self.state_processor.notification_handler:
                    self.state_processor.notification_handler.notify(
                        "error",
                        f"Error processing state: {e}",
                        {"error": str(e), "state_type": state.get("type")}
                    )
            finally:
                # Clear handler thread reference when done
                with self._handler_lock:
                    if self._current_handler_thread == threading.current_thread():
                        self._current_handler_thread = None

        handler_thread = threading.Thread(target=run_handler, daemon=True, name=f"TurnHandler-{state.get('turn', '?')}")
        with self._handler_lock:
            self._current_handler_thread = handler_thread
        handler_thread.start()
        self._log.debug(f"Started handler thread for turn {state.get('turn', '?')}")
