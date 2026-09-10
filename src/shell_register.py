"""Install and register the per-user Explorer context-menu COM host."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import winreg
from pathlib import Path

CLSID = "{8F3C2A11-9B4E-4D6A-9C71-2E7A1B4C5D6E}"
HANDLER_KEY = (
    r"Software\Classes\AllFilesystemObjects\shellex"
    r"\ContextMenuHandlers\NaiwaDestroy"
)
CLSID_KEY = rf"Software\Classes\CLSID\{CLSID}\InprocServer32"


def _source_dir() -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "NaiwaShell")
    candidates.append(
        Path(__file__).resolve().parent.parent
        / "shell"
        / "NaiwaShell"
        / "bin"
        / "Release"
        / "net8.0-windows"
    )
    for candidate in candidates:
        if (candidate / "NaiwaShell.comhost.dll").is_file():
            return candidate
    return None


def _registry_matches(comhost: Path) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLSID_KEY) as key:
            registered, _ = winreg.QueryValueEx(key, None)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, HANDLER_KEY) as key:
            handler, _ = winreg.QueryValueEx(key, None)
        return (
            os.path.normcase(str(registered)) == os.path.normcase(str(comhost))
            and str(handler).upper() == CLSID
        )
    except OSError:
        return False


def _notify_shell() -> None:
    SHCNE_ASSOCCHANGED = 0x08000000
    SHCNF_IDLIST = 0
    ctypes.windll.shell32.SHChangeNotify(
        SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
    )


def _ensure_private_dotnet_root() -> None:
    """Expose a user-local .NET install to future Explorer processes."""
    local_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "dotnet"
    if not (local_root / "host" / "fxr").is_dir():
        return

    value = str(local_root)
    os.environ.setdefault("DOTNET_ROOT", value)
    os.environ.setdefault("DOTNET_ROOT_X64", value)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        winreg.SetValueEx(key, "DOTNET_ROOT", 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "DOTNET_ROOT_X64", 0, winreg.REG_SZ, value)

    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_size_t()
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST,
        WM_SETTINGCHANGE,
        0,
        ctypes.c_wchar_p("Environment"),
        SMTO_ABORTIFHUNG,
        1000,
        ctypes.byref(result),
    )


def register_shell_extension() -> bool:
    """Copy the COM host to LocalAppData and write HKCU registration.

    Failure is deliberately non-fatal: the desktop pet must still start.
    """
    if os.environ.get("NAIWA_SKIP_SHELL_REG") == "1":
        return False

    _ensure_private_dotnet_root()
    source = _source_dir()
    if source is None:
        print("NaiwaShell build output not found; context menu is unavailable.", file=sys.stderr)
        return False

    destination = Path(os.environ["LOCALAPPDATA"]) / "Naiwa" / "shell"
    destination.mkdir(parents=True, exist_ok=True)
    comhost = destination / "NaiwaShell.comhost.dll"

    try:
        if not _registry_matches(comhost):
            for item in source.iterdir():
                if item.is_file():
                    shutil.copy2(item, destination / item.name)

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CLSID_KEY) as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(comhost))
                winreg.SetValueEx(
                    key, "ThreadingModel", 0, winreg.REG_SZ, "Apartment"
                )
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, HANDLER_KEY) as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, CLSID)
            _notify_shell()
        return True
    except (OSError, KeyError) as exc:
        print(f"Unable to register NaiwaShell: {exc}", file=sys.stderr)
        return False

