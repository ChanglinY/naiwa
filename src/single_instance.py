from __future__ import annotations

import ctypes
from ctypes import wintypes

MUTEX_NAME = r"Local\NaiwaPet.Running"
ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_create_mutex = _kernel32.CreateMutexW
_create_mutex.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_create_mutex.restype = wintypes.HANDLE
_close_handle = _kernel32.CloseHandle
_close_handle.argtypes = [wintypes.HANDLE]
_close_handle.restype = wintypes.BOOL


class SingleInstance:
    """Hold a per-login-session mutex for the pet process lifetime."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._handle: int | None = None
        self.acquired = False
        self.error_code = 0
        if not name:
            raise ValueError("mutex name must not be empty")

        ctypes.set_last_error(0)
        handle = _create_mutex(None, False, name)
        self.error_code = ctypes.get_last_error()
        if not handle:
            self.acquired = False
            return
        if self.error_code == ERROR_ALREADY_EXISTS:
            _close_handle(handle)
            self.acquired = False
            return

        self._handle = handle
        self.acquired = True

    def close(self) -> None:
        """Release this process's handle; safe to call more than once."""
        handle, self._handle = self._handle, None
        if handle:
            _close_handle(handle)
        self.acquired = False

    def __enter__(self) -> SingleInstance:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
