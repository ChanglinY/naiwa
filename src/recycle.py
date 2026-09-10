from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path

CLSID_FILE_OPERATION = "{3AD05575-8857-4850-9277-11B85BDB8E09}"
IID_IFILE_OPERATION = "{947AAB5F-0A5C-4C13-B4D6-4BF7836FC9F8}"
IID_ISHELL_ITEM = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1
RPC_E_CHANGED_MODE = 0x80010106

FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOFX_RECYCLEONDELETE = 0x00080000
FILE_OPERATION_FLAGS = (
    FOF_SILENT
    | FOF_NOCONFIRMATION
    | FOF_ALLOWUNDO
    | FOF_NOERRORUI
    | FOFX_RECYCLEONDELETE
)


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


def _failed(hresult: int) -> bool:
    return hresult < 0


def _hresult_text(hresult: int) -> str:
    return f"HRESULT 0x{hresult & 0xFFFFFFFF:08X}"


def _method(
    interface: ctypes.c_void_p,
    index: int,
    restype: type[ctypes._SimpleCData],  # type: ignore[attr-defined]
    *argtypes: object,
) -> object:
    vtable = ctypes.cast(
        interface,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(vtable[index])


def _release(interface: ctypes.c_void_p) -> None:
    if interface.value:
        release = _method(interface, 2, wintypes.ULONG)
        release(interface)  # type: ignore[operator]
        interface.value = None


def _file_operation_recycle(path: str) -> tuple[bool, str]:
    ole32 = ctypes.OleDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")

    co_initialize = ole32.CoInitializeEx
    co_initialize.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    co_initialize.restype = ctypes.c_long
    co_uninitialize = ole32.CoUninitialize
    co_uninitialize.argtypes = []
    co_uninitialize.restype = None

    co_create = ole32.CoCreateInstance
    co_create.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    co_create.restype = ctypes.c_long

    create_item = shell32.SHCreateItemFromParsingName
    create_item.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    create_item.restype = ctypes.c_long

    init_result = co_initialize(None, COINIT_APARTMENTTHREADED)
    init_unsigned = init_result & 0xFFFFFFFF
    should_uninitialize = not _failed(init_result)
    if _failed(init_result) and init_unsigned != RPC_E_CHANGED_MODE:
        return False, f"CoInitializeEx failed: {_hresult_text(init_result)}"

    operation = ctypes.c_void_p()
    item = ctypes.c_void_p()
    try:
        clsid = _GUID.from_string(CLSID_FILE_OPERATION)
        operation_iid = _GUID.from_string(IID_IFILE_OPERATION)
        result = co_create(
            ctypes.byref(clsid),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(operation_iid),
            ctypes.byref(operation),
        )
        if _failed(result):
            return False, f"CoCreateInstance failed: {_hresult_text(result)}"

        set_flags = _method(operation, 5, ctypes.c_long, wintypes.DWORD)
        result = set_flags(operation, FILE_OPERATION_FLAGS)  # type: ignore[operator]
        if _failed(result):
            return False, f"SetOperationFlags failed: {_hresult_text(result)}"

        shell_item_iid = _GUID.from_string(IID_ISHELL_ITEM)
        result = create_item(path, None, ctypes.byref(shell_item_iid), ctypes.byref(item))
        if _failed(result):
            return False, f"SHCreateItemFromParsingName failed: {_hresult_text(result)}"

        delete_item = _method(
            operation,
            18,
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        result = delete_item(operation, item, None)  # type: ignore[operator]
        if _failed(result):
            return False, f"DeleteItem failed: {_hresult_text(result)}"

        perform = _method(operation, 21, ctypes.c_long)
        result = perform(operation)  # type: ignore[operator]
        if _failed(result):
            return False, f"PerformOperations failed: {_hresult_text(result)}"

        aborted = wintypes.BOOL()
        get_aborted = _method(
            operation,
            22,
            ctypes.c_long,
            ctypes.POINTER(wintypes.BOOL),
        )
        result = get_aborted(operation, ctypes.byref(aborted))  # type: ignore[operator]
        if _failed(result):
            return False, f"GetAnyOperationsAborted failed: {_hresult_text(result)}"
        if aborted.value:
            return False, "Recycle operation was cancelled"
        return True, ""
    finally:
        _release(item)
        _release(operation)
        if should_uninitialize:
            co_uninitialize()


def send_to_recycle_bin(path: str | os.PathLike[str]) -> tuple[bool, str]:
    """Move one file, directory, or shortcut to the Windows Recycle Bin."""
    if os.name != "nt":
        return False, "Recycle Bin is only supported on Windows"
    try:
        value = os.fspath(path)
    except TypeError as exc:
        return False, str(exc)
    if not value or "\0" in value:
        return False, "Invalid path"

    try:
        absolute = str(Path(value).resolve(strict=True))
    except (FileNotFoundError, OSError) as exc:
        return False, f"Path is unavailable: {exc}"

    try:
        return _file_operation_recycle(absolute)
    except (OSError, ValueError, ctypes.ArgumentError) as exc:
        return False, f"Recycle Bin API failed: {exc}"
