from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path

FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
FOLDERID_PUBLIC_DESKTOP = "{C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}"


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> _GUID:
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def _known_folder(folder_id: str) -> Path | None:
    """Return a Windows Known Folder path, or ``None`` if it is unavailable."""
    if os.name != "nt":
        return None

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    get_path = shell32.SHGetKnownFolderPath
    get_path.argtypes = [
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_path.restype = ctypes.c_long
    free = ole32.CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None

    guid = _GUID.from_string(folder_id)
    raw_path = ctypes.c_void_p()
    result = get_path(ctypes.byref(guid), 0, None, ctypes.byref(raw_path))
    if result < 0 or not raw_path.value:
        return None
    try:
        value = ctypes.cast(raw_path, ctypes.c_wchar_p).value
        return Path(value) if value else None
    finally:
        free(raw_path)


def desktop_roots() -> tuple[Path, Path]:
    """Return the current user's and public desktop directories."""
    user_fallback = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    public_base = os.environ.get("PUBLIC")
    if public_base:
        public_fallback = Path(public_base) / "Desktop"
    else:
        public_fallback = Path(os.environ.get("SystemDrive", "C:")) / "Users" / "Public" / "Desktop"
    return (
        _known_folder(FOLDERID_DESKTOP) or user_fallback,
        _known_folder(FOLDERID_PUBLIC_DESKTOP) or public_fallback,
    )


def normalize_path(path: str | os.PathLike[str]) -> str:
    """Return an absolute, case-normalized path suitable for comparisons."""
    value = os.fspath(path)
    if not value:
        raise ValueError("path must not be empty")
    if "\0" in value:
        raise ValueError("path must not contain NUL")

    expanded = os.path.expanduser(os.path.expandvars(value))
    try:
        absolute = str(Path(expanded).resolve(strict=False))
    except (OSError, RuntimeError):
        absolute = os.path.abspath(expanded)
    return os.path.normcase(os.path.normpath(absolute))


def paths_equal(
    first: str | os.PathLike[str],
    second: str | os.PathLike[str],
) -> bool:
    """Compare two paths using Windows filesystem comparison semantics."""
    return normalize_path(first) == normalize_path(second)


def is_desktop_path(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* is a desktop root or one of its descendants."""
    target = normalize_path(path)
    for root in desktop_roots():
        normalized_root = normalize_path(root)
        try:
            if os.path.commonpath((target, normalized_root)) == normalized_root:
                return True
        except ValueError:
            continue
    return False
