from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

PIPE_NAME = r"\\.\pipe\NaiwaDestroy"
PIPE_SHORT = "NaiwaDestroy"
MAX_MESSAGE_BYTES = 32 * 1024

PIPE_ACCESS_INBOUND = 0x00000001
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
ERROR_PIPE_CONNECTED = 535
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
THREAD_TERMINATE = 0x0001
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_create_named_pipe = _kernel32.CreateNamedPipeW
_create_named_pipe.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
]
_create_named_pipe.restype = wintypes.HANDLE

_connect_named_pipe = _kernel32.ConnectNamedPipe
_connect_named_pipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
_connect_named_pipe.restype = wintypes.BOOL

_disconnect_named_pipe = _kernel32.DisconnectNamedPipe
_disconnect_named_pipe.argtypes = [wintypes.HANDLE]
_disconnect_named_pipe.restype = wintypes.BOOL

_create_file = _kernel32.CreateFileW
_create_file.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_create_file.restype = wintypes.HANDLE

_wait_named_pipe = _kernel32.WaitNamedPipeW
_wait_named_pipe.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
_wait_named_pipe.restype = wintypes.BOOL

_read_file = _kernel32.ReadFile
_read_file.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
_read_file.restype = wintypes.BOOL

_write_file = _kernel32.WriteFile
_write_file.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
_write_file.restype = wintypes.BOOL

_close_handle = _kernel32.CloseHandle
_close_handle.argtypes = [wintypes.HANDLE]
_close_handle.restype = wintypes.BOOL

_open_thread = _kernel32.OpenThread
_open_thread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_open_thread.restype = wintypes.HANDLE

_cancel_synchronous_io = _kernel32.CancelSynchronousIo
_cancel_synchronous_io.argtypes = [wintypes.HANDLE]
_cancel_synchronous_io.restype = wintypes.BOOL


def _is_invalid_handle(handle: int | None) -> bool:
    return handle in (None, 0, INVALID_HANDLE_VALUE)


def _write_payload(payload: bytes, timeout_ms: int) -> bool:
    deadline = time.monotonic() + max(timeout_ms, 0) / 1000
    while True:
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        if not _wait_named_pipe(PIPE_NAME, remaining_ms):
            if time.monotonic() >= deadline or timeout_ms <= 0:
                return False
            time.sleep(0.005)
            continue

        handle = _create_file(
            PIPE_NAME,
            GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if not _is_invalid_handle(handle):
            break
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.005)

    try:
        buffer = ctypes.create_string_buffer(payload)
        written = wintypes.DWORD()
        ok = _write_file(
            handle,
            buffer,
            len(payload),
            ctypes.byref(written),
            None,
        )
        return bool(ok) and written.value == len(payload)
    finally:
        _close_handle(handle)


def send_destroy_path(path: str, timeout_ms: int = 300) -> bool:
    """Send one UTF-8, newline-delimited path to the local destroy server."""
    if not isinstance(path, str) or not path or "\n" in path or "\r" in path or "\0" in path:
        return False
    payload = (path + "\n").encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        return False
    return _write_payload(payload, timeout_ms)


def _cancel_thread_io(thread: threading.Thread) -> None:
    native_id = thread.native_id
    if native_id is None:
        return
    handle = _open_thread(THREAD_TERMINATE, False, native_id)
    if _is_invalid_handle(handle):
        return
    try:
        _cancel_synchronous_io(handle)
    finally:
        _close_handle(handle)


class DestroyPipeServer:
    """Single-client-at-a-time local named-pipe server."""

    def __init__(self, on_path: Callable[[str], None]) -> None:
        self._on_path = on_path
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handle_lock = threading.Lock()
        self._pipe: int | None = None
        self.error_code = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self.ready.clear()
        self._stop.clear()
        self.error_code = 0
        self._thread = threading.Thread(
            target=self._loop,
            name="NaiwaDestroyPipe",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self.running and self.ready.is_set():
            _write_payload(b"\n", 200)
        thread = self._thread
        if thread is not None:
            _cancel_thread_io(thread)
            thread.join(timeout)
        if thread is not None and not thread.is_alive():
            self._thread = None
        self.ready.clear()

    def _loop(self) -> None:
        while not self._stop.is_set():
            ctypes.set_last_error(0)
            handle = _create_named_pipe(
                PIPE_NAME,
                PIPE_ACCESS_INBOUND,
                PIPE_TYPE_BYTE
                | PIPE_READMODE_BYTE
                | PIPE_WAIT
                | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                MAX_MESSAGE_BYTES,
                MAX_MESSAGE_BYTES,
                0,
                None,
            )
            if _is_invalid_handle(handle):
                self.error_code = ctypes.get_last_error()
                return

            with self._handle_lock:
                self._pipe = handle
            self.ready.set()
            connected = False
            try:
                connected = bool(_connect_named_pipe(handle, None))
                if not connected:
                    connected = ctypes.get_last_error() == ERROR_PIPE_CONNECTED
                if not connected or self._stop.is_set():
                    continue
                path = self._read_path(handle)
                if path is not None:
                    try:
                        self._on_path(path)
                    except Exception:
                        # A consumer failure must not terminate the IPC listener.
                        pass
            finally:
                if connected:
                    _disconnect_named_pipe(handle)
                _close_handle(handle)
                with self._handle_lock:
                    if self._pipe == handle:
                        self._pipe = None

    @staticmethod
    def _read_path(handle: int) -> str | None:
        data = bytearray()
        buffer = ctypes.create_string_buffer(4096)
        while len(data) < MAX_MESSAGE_BYTES:
            read = wintypes.DWORD()
            ok = _read_file(
                handle,
                buffer,
                len(buffer),
                ctypes.byref(read),
                None,
            )
            if not ok or read.value == 0:
                break
            data.extend(buffer.raw[: read.value])
            if b"\n" in data:
                break

        if b"\n" not in data:
            return None
        raw = bytes(data).split(b"\n", 1)[0]
        if not raw or b"\0" in raw:
            return None
        try:
            return raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None


class DestroyIpc(QObject):
    """Qt bridge; worker-thread emissions queue safely to QObject receivers."""

    path_received = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = DestroyPipeServer(self.path_received.emit)

    @property
    def ready(self) -> threading.Event:
        return self._server.ready

    def start(self) -> None:
        self._server.start()

    def stop(self) -> None:
        self._server.stop()
