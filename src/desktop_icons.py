"""从 Explorer 桌面 ListView 读取图标屏幕矩形、标签和文件路径。"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

if os.name == "nt":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.FindWindowExW.argtypes = [
        wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR
    ]
    _user32.FindWindowExW.restype = wintypes.HWND
    _user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.MapWindowPoints.argtypes = [
        wintypes.HWND, wintypes.HWND, wintypes.LPVOID, wintypes.UINT
    ]
    _user32.MapWindowPoints.restype = ctypes.c_int
    _kernel32.OpenProcess.argtypes = [
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
    ]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.VirtualAllocEx.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _kernel32.VirtualAllocEx.restype = wintypes.LPVOID
    _kernel32.VirtualFreeEx.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD
    ]
    _kernel32.VirtualFreeEx.restype = wintypes.BOOL
    _kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.LPVOID,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.ReadProcessMemory.restype = wintypes.BOOL
    _kernel32.WriteProcessMemory.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.LPCVOID,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.WriteProcessMemory.restype = wintypes.BOOL
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.IsWow64Process.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)
    ]
    _kernel32.IsWow64Process.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:
    _user32 = None
    _kernel32 = None

LVM_FIRST = 0x1000
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_GETITEMRECT = LVM_FIRST + 14
LVM_GETITEMTEXTW = LVM_FIRST + 115
LVIR_BOUNDS = 0
LVIF_TEXT = 0x0001
SMTO_ABORTIFHUNG = 0x0002
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
TEXT_CHARS = 520


class _LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT),
        ("iItem", ctypes.c_int),
        ("iSubItem", ctypes.c_int),
        ("state", wintypes.UINT),
        ("stateMask", wintypes.UINT),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", wintypes.LPARAM),
        ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int),
        ("cColumns", wintypes.UINT),
        ("puColumns", ctypes.c_void_p),
        ("piColFmt", ctypes.c_void_p),
        ("iGroup", ctypes.c_int),
    ]


def _send(hwnd: int, message: int, wparam: int = 0, lparam: int = 0) -> int | None:
    result = ctypes.c_size_t()
    ok = _user32.SendMessageTimeoutW(
        hwnd,
        message,
        wparam,
        lparam,
        SMTO_ABORTIFHUNG,
        1000,
        ctypes.byref(result),
    )
    return int(result.value) if ok else None


def _find_listview() -> int:
    progman = _user32.FindWindowW("Progman", None)

    def below(parent: int) -> int:
        view = _user32.FindWindowExW(parent, 0, "SHELLDLL_DefView", None)
        if not view:
            return 0
        return int(_user32.FindWindowExW(view, 0, "SysListView32", None) or 0)

    found = below(progman) if progman else 0
    if found:
        return found

    result = 0
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def enum_window(hwnd, _lparam):
        nonlocal result
        result = below(hwnd)
        return not bool(result)

    _user32.EnumWindows(enum_window, 0)
    return result


def _same_bitness(process: int) -> bool:
    """LVITEM contains pointers, so its layout must match Explorer's process."""
    current_wow64 = wintypes.BOOL()
    target_wow64 = wintypes.BOOL()
    if not _kernel32.IsWow64Process(
        _kernel32.GetCurrentProcess(), ctypes.byref(current_wow64)
    ):
        return False
    if not _kernel32.IsWow64Process(process, ctypes.byref(target_wow64)):
        return False
    return bool(current_wow64.value) == bool(target_wow64.value)


def _write(process: int, address: int, value) -> bool:
    written = ctypes.c_size_t()
    return bool(
        _kernel32.WriteProcessMemory(
            process,
            address,
            ctypes.byref(value),
            ctypes.sizeof(value),
            ctypes.byref(written),
        )
        and written.value == ctypes.sizeof(value)
    )


def _read(process: int, address: int, value) -> bool:
    read = ctypes.c_size_t()
    return bool(
        _kernel32.ReadProcessMemory(
            process,
            address,
            ctypes.byref(value),
            ctypes.sizeof(value),
            ctypes.byref(read),
        )
        and read.value == ctypes.sizeof(value)
    )


def _read_icon(
    listview: int,
    process: int,
    remote: int,
    text_address: int,
    rect_address: int,
    index: int,
) -> tuple[str, wintypes.RECT] | None:
    rect = wintypes.RECT(LVIR_BOUNDS, 0, 0, 0)
    if not _write(process, rect_address, rect):
        return None
    if not _send(listview, LVM_GETITEMRECT, index, rect_address):
        return None
    if not _read(process, rect_address, rect):
        return None

    item = _LVITEMW()
    item.mask = LVIF_TEXT
    item.iItem = index
    item.iSubItem = 0
    item.pszText = text_address
    item.cchTextMax = TEXT_CHARS
    name = ""
    if _write(process, remote, item):
        copied = _send(listview, LVM_GETITEMTEXTW, index, remote)
        if copied is not None:
            text = ctypes.create_unicode_buffer(TEXT_CHARS)
            if _read(process, text_address, text):
                name = text.value

    # Two POINTs are layout-compatible with RECT and convert client to screen pixels.
    if not _user32.MapWindowPoints(listview, 0, ctypes.byref(rect), 2):
        # A zero return is also valid when no translation is needed; desktop should
        # normally have a non-zero offset, so preserve the coordinates either way.
        pass
    return name, rect


def _desktop_roots() -> tuple[Path, ...]:
    try:
        from .paths import desktop_roots

        return tuple(desktop_roots())
    except Exception:
        return (
            Path(os.path.expandvars(r"%USERPROFILE%\Desktop")),
            Path(os.path.expandvars(r"%PUBLIC%\Desktop")),
        )


def _resolve_path(name: str, roots: tuple[Path, ...]) -> str:
    if not name:
        return ""
    for root in roots:
        candidate = root / name
        if candidate.exists():
            return str(candidate)

    folded = name.casefold()
    matches: list[Path] = []
    for root in roots:
        try:
            for candidate in root.iterdir():
                if candidate.name.casefold() == folded or candidate.stem.casefold() == folded:
                    matches.append(candidate)
        except OSError:
            continue
    return str(matches[0]) if len(matches) == 1 else ""


def list_desktop_icons() -> list:
    """返回 ``IconHit`` 列表；任何 Win32/Explorer 读取失败都安全返回空列表。"""
    if os.name != "nt":
        return []
    process = 0
    remote = 0
    try:
        from .hit import IconHit

        listview = _find_listview()
        if not listview:
            return []

        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(listview, ctypes.byref(pid))
        if not pid.value:
            return []
        process = _kernel32.OpenProcess(
            PROCESS_VM_OPERATION
            | PROCESS_VM_READ
            | PROCESS_VM_WRITE
            | PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid.value,
        )
        if not process or not _same_bitness(process):
            return []

        item_size = ctypes.sizeof(_LVITEMW)
        text_size = TEXT_CHARS * ctypes.sizeof(ctypes.c_wchar)
        text_offset = (item_size + 7) & ~7
        rect_offset = (text_offset + text_size + 7) & ~7
        total_size = rect_offset + ctypes.sizeof(wintypes.RECT)
        remote = _kernel32.VirtualAllocEx(
            process, None, total_size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not remote:
            return []

        count = _send(listview, LVM_GETITEMCOUNT)
        if count is None or count < 0 or count > 10000:
            return []
        roots = _desktop_roots()
        icons = []
        for index in range(count):
            result = _read_icon(
                listview,
                process,
                remote,
                remote + text_offset,
                remote + rect_offset,
                index,
            )
            if result is None:
                continue
            name, rect = result
            width = max(0, rect.right - rect.left)
            height = max(0, rect.bottom - rect.top)
            if width and height:
                icons.append(
                    IconHit(
                        _resolve_path(name, roots),
                        name,
                        rect.left,
                        rect.top,
                        width,
                        height,
                    )
                )
        return icons
    except Exception:
        return []
    finally:
        if remote and process:
            _kernel32.VirtualFreeEx(process, remote, 0, MEM_RELEASE)
        if process:
            _kernel32.CloseHandle(process)
