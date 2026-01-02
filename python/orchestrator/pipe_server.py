from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable, Optional

from .logging_setup import get_logger


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


OnMessage = Callable[[bytes], Optional[bytes]]


class NamedPipeServer:
    """Single-client named-pipe server (message mode).

    Accepts one client at a time, processes messages synchronously with
    an `on_message` callback, and optionally replies per message.
    """

    def __init__(self, pipe_name: str, on_message: OnMessage):
        if not pipe_name.startswith("\\\\.\\pipe\\"):
            raise ValueError("pipe_name must start with \\\\.\\pipe\\")
        self.pipe_name = pipe_name
        self.on_message = on_message
        self._running = False
        self._log = get_logger()
        self._handle: Optional[int] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._serve_loop()

    def stop(self) -> None:
        self._running = False
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
                # Ensure message read mode (should already be set by creation flags)
                mode = wintypes.DWORD(WinAPI.PIPE_READMODE_MESSAGE)
                WinAPI.SetNamedPipeHandleState(h, ctypes.byref(mode), None, None)
                self._log.info("Client connected")

                self._client_loop(h)
            finally:
                self._close()

    def _client_loop(self, h: int) -> None:
        buf = (ctypes.c_char * WinAPI.BUFSIZE)()
        bytes_read = wintypes.DWORD(0)
        while self._running:
            ok = WinAPI.ReadFile(h, buf, WinAPI.BUFSIZE, ctypes.byref(bytes_read), None)
            if not ok:
                err = ctypes.get_last_error()
                if err == WinAPI.ERROR_MORE_DATA:
                    # Message larger than buffer; read the remainder next
                    chunk = bytes(buf[: bytes_read.value])
                    self._dispatch(h, chunk)
                    continue
                self._log.info(f"Client disconnected or read error: {err}")
                break
            if bytes_read.value == 0:
                self._log.info("Client closed pipe")
                break
            data = bytes(buf[: bytes_read.value])
            self._dispatch(h, data)

    def _dispatch(self, h: int, data: bytes) -> None:
        try:
            reply = self.on_message(data)
        except Exception as e:
            self._log.error(f"Handler error: {e}")
            reply = None
        if reply:
            self._write(h, reply)

    def _write(self, h: int, data: bytes) -> None:
        bytes_written = wintypes.DWORD(0)
        ok = WinAPI.WriteFile(h, data, len(data), ctypes.byref(bytes_written), None)
        if not ok or bytes_written.value != len(data):
            err = ctypes.get_last_error()
            self._log.error(f"Write failed: {err}")

