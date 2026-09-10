# Desktop Destroy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a running Naiwa show “召唤奶蛙摧毁” on desktop icon right-click, confirm via a fullscreen overlay, crawl to the icon, play a destroy animation, then send that item to the Recycle Bin.

**Architecture:** A C# COM `IContextMenu` DLL (loaded by Explorer) only decides whether to show the verb and writes one UTF-8 path to a named pipe. The existing PySide6 pet holds a mutex, listens on the pipe, shows a click-capturing overlay, hit-tests desktop icons, reuses crawl/chase, then calls `IFileOperation` to recycle. The COM host DLL is copied to `%LOCALAPPDATA%\Naiwa\` so Explorer does not load a PyInstaller temp path.

**Tech Stack:** Python 3.14, PySide6, ctypes (Win32 / COM), C# `net8.0-windows` with `EnableComHosting`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-desktop-destroy-design.md`

**Git:** This repo may not have `.git` yet. If `git status` fails, skip every Commit step (do not `git init` unless the user asks).

**Constants (do not rename):**

- Mutex: `Local\NaiwaPet.Running`
- Pipe: `\\.\pipe\NaiwaDestroy` (client name `NaiwaDestroy`)
- CLSID: `{8F3C2A11-9B4E-4D6A-9C71-2E7A1B4C5D6E}`
- Menu text: `召唤奶蛙摧毁`
- Skip COM register: env `NAIWA_SKIP_SHELL_REG=1`

---

## File map

| Path | Responsibility |
|---|---|
| `src/paths.py` | Desktop roots, path normalize/equality |
| `src/hit.py` | Point-in-rect hit test against icon records |
| `src/recycle.py` | `IFileOperation` → Recycle Bin |
| `src/single_instance.py` | Named mutex; second instance exits |
| `src/destroy_ipc.py` | Named-pipe server; Qt signal with path |
| `src/desktop_icons.py` | Enumerate desktop `SysListView32` icons |
| `src/destroy_overlay.py` | Fullscreen confirm overlay |
| `src/destroy_session.py` | Orchestrate overlay → chase → anim → recycle |
| `src/shell_register.py` | Copy COM host DLL + HKCU `regsvr32 /i:user` |
| `src/config.py` | `destroy` action + overlay copy |
| `src/behavior.py` | Freeze, destroy-chase, arrive → destroy anim |
| `src/pet_window.py` | Wire session; mouse-chase vs destroy target |
| `src/main.py` | Mutex, IPC, optional COM register |
| `shell/NaiwaShell/` | C# COM context menu |
| `tests/` | Unit tests |
| `tools/smoke_test.py` | Set `NAIWA_SKIP_SHELL_REG=1` |
| `requirements-dev.txt` | pytest |
| `README.md` | How to build/register the shell extension |

---

### Task 1: Path helpers (TDD)

**Files:**
- Create: `src/paths.py`
- Create: `tests/test_paths.py`
- Create: `requirements-dev.txt`

- [ ] **Step 1: Add pytest**

`requirements-dev.txt`:

```
pytest==8.4.1
```

Run: `.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`

- [ ] **Step 2: Write failing tests**

```python
# tests/test_paths.py
from pathlib import Path

from src.paths import is_desktop_path, paths_equal, normalize_path


def test_normalize_strips_trailing_slash_and_case(tmp_path: Path) -> None:
    a = tmp_path / "Foo"
    a.mkdir()
    assert normalize_path(str(a) + "\\") == normalize_path(str(a))


def test_paths_equal_same_file(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert paths_equal(str(f), str(f.resolve()))


def test_is_desktop_path_true_for_nested(monkeypatch, tmp_path: Path) -> None:
    desk = tmp_path / "Desktop"
    pub = tmp_path / "PublicDesktop"
    desk.mkdir()
    pub.mkdir()
    nested = desk / "folder" / "x.txt"
    nested.parent.mkdir()
    nested.write_text("x", encoding="utf-8")
    monkeypatch.setattr("src.paths.desktop_roots", lambda: (desk, pub))
    assert is_desktop_path(str(nested)) is True


def test_is_desktop_path_false_outside(monkeypatch, tmp_path: Path) -> None:
    desk = tmp_path / "Desktop"
    pub = tmp_path / "PublicDesktop"
    desk.mkdir()
    pub.mkdir()
    other = tmp_path / "Downloads" / "x.txt"
    other.parent.mkdir()
    other.write_text("x", encoding="utf-8")
    monkeypatch.setattr("src.paths.desktop_roots", lambda: (desk, pub))
    assert is_desktop_path(str(other)) is False
```

- [ ] **Step 3: Run tests (expect fail)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paths.py -v`

Expected: `ModuleNotFoundError` or collection error for `src.paths`

- [ ] **Step 4: Implement**

```python
# src/paths.py
from __future__ import annotations

import os
from pathlib import Path


def desktop_roots() -> tuple[Path, Path]:
    home = Path(os.path.expandvars("%USERPROFILE%")) / "Desktop"
    public = Path(os.path.expandvars("%PUBLIC%")) / "Desktop"
    known_user = Path(os.path.expandvars("%USERPROFILE%"))
    # Prefer Known Folder via ctypes when available
    user = _known_folder("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}") or home
    pub = _known_folder("{C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}") or public
    return user, pub


def _known_folder(folder_id: str) -> Path | None:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def parse(s: str) -> GUID:
        h = s.strip("{}").split("-")
        g = GUID()
        g.Data1 = int(h[0], 16)
        g.Data2 = int(h[1], 16)
        g.Data3 = int(h[2], 16)
        blob = bytes.fromhex(h[3] + h[4])
        for i, b in enumerate(blob):
            g.Data4[i] = b
        return g

    SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
    SHGetKnownFolderPath.restype = ctypes.HRESULT
    path_ptr = ctypes.c_wchar_p()
    fid = parse(folder_id)
    hr = SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(path_ptr))
    if hr != 0 or not path_ptr.value:
        return None
    p = Path(path_ptr.value)
    ctypes.windll.ole32.CoTaskMemFree(path_ptr)
    return p


def normalize_path(path: str) -> str:
    p = Path(path)
    try:
        p = p.resolve()
    except OSError:
        p = Path(os.path.normpath(path))
    return os.path.normcase(str(p).rstrip("\\/"))


def paths_equal(a: str, b: str) -> bool:
    return normalize_path(a) == normalize_path(b)


def is_desktop_path(path: str) -> bool:
    target = normalize_path(path)
    for root in desktop_roots():
        prefix = normalize_path(str(root))
        if target == prefix or target.startswith(prefix + os.sep):
            return True
    return False
```

- [ ] **Step 5: Run tests (expect pass)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paths.py -v`

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/paths.py tests/test_paths.py requirements-dev.txt
git commit -m "feat: add desktop path helpers"
```

---

### Task 2: Icon hit-test helper (TDD)

**Files:**
- Create: `src/hit.py`
- Create: `tests/test_hit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_hit.py
from src.hit import IconHit, hit_icon

ICONS = [
    IconHit("C:\\Users\\a\\Desktop\\a.txt", "a.txt", 10, 10, 50, 70),
    IconHit("C:\\Users\\a\\Desktop\\b.txt", "b.txt", 80, 10, 50, 70),
]


def test_hit_first() -> None:
    got = hit_icon(ICONS, 20, 20)
    assert got is not None
    assert got.name == "a.txt"


def test_miss_empty() -> None:
    assert hit_icon(ICONS, 0, 0) is None


def test_hit_prefers_first_containing() -> None:
    got = hit_icon(ICONS, 85, 15)
    assert got is not None
    assert got.name == "b.txt"
```

- [ ] **Step 2: Run (expect fail)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_hit.py -v`

- [ ] **Step 3: Implement**

```python
# src/hit.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IconHit:
    path: str
    name: str
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


def hit_icon(icons: list[IconHit], px: int, py: int) -> IconHit | None:
    for icon in icons:
        if icon.contains(px, py):
            return icon
    return None
```

- [ ] **Step 4: Run (expect pass)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_hit.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/hit.py tests/test_hit.py
git commit -m "feat: add desktop icon hit testing"
```

---

### Task 3: Recycle Bin via IFileOperation (TDD)

**Files:**
- Create: `src/recycle.py`
- Create: `tests/test_recycle.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_recycle.py
from pathlib import Path

from src.recycle import send_to_recycle_bin


def test_send_temp_file_to_recycle(tmp_path: Path) -> None:
    f = tmp_path / "naiwa_recycle_test.txt"
    f.write_text("recycle-me", encoding="utf-8")
    ok, err = send_to_recycle_bin(str(f))
    assert ok, err
    assert not f.exists()
```

- [ ] **Step 2: Run (expect fail)**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recycle.py -v`

- [ ] **Step 3: Implement `src/recycle.py`**

Use ctypes COM `IFileOperation` (`CLSID_FileOperation` `{3AD05575-8857-4850-9277-11B85BDB8E09}`, `IID_IFileOperation` `{947AAB5F-0A5C-4C13-B4D6-4BF7836FC9F8}`). Flags: `FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT` (`0x1544`). `IFileOperation.DeleteItem` then `PerformOperations`. Return `(True, "")` on HRESULT 0, else `(False, hex(hr) or message)`. Do **not** use `os.remove`. Shortcuts: pass the `.lnk` path unchanged.

Minimal reliable approach if full vtable wrapping is too brittle: call `shell32.SHFileOperationW` with `FO_DELETE` and `FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT` via a `SHFILEOPSTRUCTW` (double-null-terminated `pFrom`). Spec prefers IFileOperation; SHFileOperationW is acceptable if IFileOperation ctypes vtable fails in practice — keep the public function `send_to_recycle_bin(path: str) -> tuple[bool, str]`.

```python
# src/recycle.py
from __future__ import annotations

import ctypes
from ctypes import wintypes

FO_DELETE = 3
FOF_SILENT = 4
FOF_NOCONFIRMATION = 16
FOF_ALLOWUNDO = 64
FOF_NOERRORUI = 1024


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.USHORT),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def send_to_recycle_bin(path: str) -> tuple[bool, str]:
    buf = path + "\0\0"
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = buf
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        return False, f"SHFileOperationW rc={rc} aborted={op.fAnyOperationsAborted}"
    return True, ""
```

- [ ] **Step 4: Run test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recycle.py -v`

Expected: PASS. File gone from `tmp_path`; it should appear in Recycle Bin.

- [ ] **Step 5: Commit**

```bash
git add src/recycle.py tests/test_recycle.py
git commit -m "feat: send files to recycle bin"
```

---

### Task 4: Single-instance mutex

**Files:**
- Create: `src/single_instance.py`
- Create: `tests/test_single_instance.py`
- Modify: `src/main.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_single_instance.py
from src.single_instance import SingleInstance


def test_second_acquire_fails() -> None:
    a = SingleInstance()
    assert a.acquired is True
    b = SingleInstance()
    assert b.acquired is False
    a.close()
    c = SingleInstance()
    assert c.acquired is True
    c.close()
```

- [ ] **Step 2: Implement**

```python
# src/single_instance.py
from __future__ import annotations

import ctypes
from ctypes import wintypes

MUTEX_NAME = "Local\\NaiwaPet.Running"
ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.windll.kernel32
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetLastError.restype = wintypes.DWORD


class SingleInstance:
    def __init__(self) -> None:
        self._handle = _kernel32.CreateMutexW(None, True, MUTEX_NAME)
        self.acquired = _kernel32.GetLastError() != ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None
```

- [ ] **Step 3: Run pytest**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_single_instance.py -v`

- [ ] **Step 4: Wire `src/main.py`**

If not acquired, print or skip UI and `return 0`. Keep the `SingleInstance` object alive for the lifetime of `app.exec()`.

```python
def main() -> int:
    instance = SingleInstance()
    if not instance.acquired:
        return 0
    app = QApplication(sys.argv)
    ...
    try:
        return app.exec()
    finally:
        instance.close()
```

- [ ] **Step 5: Commit**

```bash
git add src/single_instance.py tests/test_single_instance.py src/main.py
git commit -m "feat: single-instance mutex for shell visibility"
```

---

### Task 5: Named-pipe IPC

**Files:**
- Create: `src/destroy_ipc.py`
- Create: `tests/test_destroy_ipc.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_destroy_ipc.py
import threading
import time

from src.destroy_ipc import DestroyPipeServer, send_destroy_path


def test_pipe_delivers_path() -> None:
    got: list[str] = []
    server = DestroyPipeServer(lambda p: got.append(p))
    server.start()
    try:
        for _ in range(50):
            if server.ready.wait(0.05):
                break
        assert send_destroy_path(r"C:\Users\a\Desktop\x.txt")
        deadline = time.time() + 2
        while not got and time.time() < deadline:
            time.sleep(0.05)
        assert got == [r"C:\Users\a\Desktop\x.txt"]
    finally:
        server.stop()
```

- [ ] **Step 2: Implement server**

```python
# src/destroy_ipc.py
from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes

PIPE_NAME = r"\\.\pipe\NaiwaDestroy"
PIPE_SHORT = "NaiwaDestroy"

PIPE_ACCESS_DUPLEX = 3
PIPE_TYPE_BYTE = 0
PIPE_READMODE_BYTE = 0
PIPE_WAIT = 0
PIPE_UNLIMITED_INSTANCES = 255
ERROR_PIPE_CONNECTED = 535
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

_k = ctypes.windll.kernel32


class DestroyPipeServer:
    def __init__(self, on_path: Callable[[str], None]) -> None:
        self._on_path = on_path
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pipe = wintypes.HANDLE(0)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Connect a dummy client so ConnectNamedPipe unblocks
        send_destroy_path("", timeout_ms=200)
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            handle = _k.CreateNamedPipeW(
                PIPE_NAME, PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                1, 4096, 4096, 0, None,
            )
            if handle == INVALID_HANDLE_VALUE:
                return
            self._pipe = handle
            self.ready.set()
            _k.ConnectNamedPipe(handle, None)
            if self._stop.is_set():
                _k.CloseHandle(handle)
                break
            data = b""
            buf = ctypes.create_string_buffer(4096)
            read = wintypes.DWORD()
            while b"\n" not in data and len(data) < 32768:
                ok = _k.ReadFile(handle, buf, 4096, ctypes.byref(read), None)
                if not ok or read.value == 0:
                    break
                data += buf.raw[: read.value]
            _k.DisconnectNamedPipe(handle)
            _k.CloseHandle(handle)
            line = data.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
            if line:
                self._on_path(line)


def send_destroy_path(path: str, timeout_ms: int = 300) -> bool:
    payload = (path + "\n").encode("utf-8")
    handle = _k.CreateFileW(
        PIPE_NAME, GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None,
    )
    if handle == INVALID_HANDLE_VALUE:
        return False
    written = wintypes.DWORD()
    ok = _k.WriteFile(handle, payload, len(payload), ctypes.byref(written), None)
    _k.CloseHandle(handle)
    return bool(ok)


class DestroyIpc:
    """Qt wrapper created in Task 10: path_received = Signal(str)."""

    def __init__(self) -> None:
        from PySide6.QtCore import QObject, Signal

        class _Hub(QObject):
            path_received = Signal(str)

        self._hub = _Hub()
        self.path_received = self._hub.path_received
        self._server = DestroyPipeServer(
            lambda p: self.path_received.emit(p)
        )

    def start(self) -> None:
        self._server.start()

    def stop(self) -> None:
        self._server.stop()
```

Note: emitting a Qt signal from a worker thread is allowed for queued connections to the GUI thread. Connect with `Qt.QueuedConnection` in Task 10.

- [ ] **Step 3: pytest pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_destroy_ipc.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/destroy_ipc.py tests/test_destroy_ipc.py
git commit -m "feat: named pipe for destroy target path"
```

---

### Task 6: Config + behavior destroy chase

**Files:**
- Modify: `src/config.py`
- Modify: `src/behavior.py`
- Create: `tests/test_behavior_destroy.py`

- [ ] **Step 1: Config additions** (exact names)

In `ACTIONS` add:

```python
"destroy": ActionSpec("destroy", "laugh", 24, loop=False),
```

In `POSE_AFTER_ACTION` add `"destroy": "belly"`.

Also add:

```python
DESTROY_CHASE_MAX_SEC = 60.0
OVERLAY_PROMPT = "你要销毁哪个文件？"
OVERLAY_WRONG = "不是这个"
OVERLAY_GONE = "已经没了"
OVERLAY_WRONG_SEC = 1.2
OVERLAY_GONE_SEC = 3.0
OVERLAY_FADE_MS = 250
SHELL_MENU_LABEL = "召唤奶蛙摧毁"
```

- [ ] **Step 2: Behavior API** (signatures must stay as written)

```python
def set_frozen(self, frozen: bool) -> None: ...
def start_destroy_chase(self) -> None: ...
def destroy_arrived(self) -> bool: ...  # True once after crawl_up from destroy chase
def begin_destroy_action(self) -> None: ...
def destroy_action_finished(self) -> bool: ...  # True once after destroy anim
```

Rules:

- `set_frozen(True)`: `update()` still advances animation but does not increment squat timer, does not `_decide_move`.
- `start_destroy_chase()`: clear queues; if squat, stand first then crawl_down; `_move_kind = "destroy"`; `_destroy_arrived = False`; chase timer `DESTROY_CHASE_MAX_SEC`; same crawl_down/chase/crawl_up as mouse chase.
- `_update_crawl_down`: `destroy` uses `_enter_chase_crawl()` like `chase`.
- `_update_chase`: treat `_move_kind == "destroy"` like chase (stop distance, facing). On arrive or timeout: `_enter_crawl_up()`.
- `_update_crawl_up` when `_move_kind == "destroy"`: set `_destroy_arrived = True`, `_move_kind = None`, then `_enter_idle(allow_extras=False)` **or** leave idle until session calls `begin_destroy_action()`. Prefer: crawl_up finished → idle; session sees `destroy_arrived()` then calls `begin_destroy_action()` which is `start_action("destroy")` plus `_watching_destroy = True`.
- `wants_chase_target()`: **only** `_move_kind == "chase"` (mouse). Destroy chase must **not** follow the mouse.
- `start_drag()`: if `_move_kind == "destroy"` or destroy action playing, still switch to DRAG (session treats drag as cancel, no recycle).

- [ ] **Step 3: Test freeze and destroy_arrived without GUI**

Drive `Behavior` with a `SpriteLibrary` if cheap; if `SpriteLibrary` needs Qt/assets, skip pixel tests and only unit-test `_move_kind` transitions with a stub library. If that is too coupled, test `set_frozen` does not change state over 1s of `update` while IDLE.

- [ ] **Step 4: Commit**

```bash
git add src/config.py src/behavior.py tests/test_behavior_destroy.py
git commit -m "feat: destroy chase states in behavior"
```

---

### Task 7: Fullscreen overlay

**Files:**
- Create: `src/destroy_overlay.py`

- [ ] **Step 1: Implement `DestroyOverlay(QWidget)`**

Flags: `FramelessWindowHint | Tool | WindowStaysOnTopHint | WindowDoesNotAcceptFocus` off (must accept clicks). `WA_TranslucentBackground`. Geometry = union of all `QApplication.screens()` virtual desktop (`QApplication.primaryScreen().virtualGeometry()`).

Paint: fill `QColor(40, 28, 22, 108)`; draw idle_belly or idle_relax pixmap at 28% opacity centered; draw prompt text in white ~22px below the face.

Signals: `confirmed()`, `cancelled()`, `wrong_click()`.

`set_prompt(text: str)` for 不是这个 / 已经没了.

Events:

- Left click → emit a new signal `clicked(int, int)` with **global** coordinates (session does hit-test). Overlay does not know the target path.
- Esc → `cancelled`
- Right click → `cancelled`
- `shake()`: 200ms horizontal wobble via QPropertyAnimation on a `_shake_x` property.

- [ ] **Step 2: Manual check later** (no pytest for QPainter). Smoke will import the class.

- [ ] **Step 3: Commit**

```bash
git add src/destroy_overlay.py
git commit -m "feat: fullscreen destroy confirm overlay"
```

---

### Task 8: Enumerate desktop icons

**Files:**
- Create: `src/desktop_icons.py`

- [ ] **Step 1: Implement `list_desktop_icons() -> list[IconHit]`**

Find the desktop `SysListView32`:

1. `FindWindowW("Progman", None)`
2. `FindWindowExW` for `SHELLDLL_DefView` / `SysListView32`
3. If missing, enum `WorkerW` windows (same DefView search). Sending `0x052C` to Progman is allowed once if DefView is missing.

For each item `i in 0..LVM_GETITEMCOUNT-1`:

- `LVM_GETITEMRECT` (code 0x100E) with `LVIR_BOUNDS=0` — `RECT` in listview client coords; `MapWindowPoints` to screen.
- Label via `LVM_GETITEMTEXTW`. Cross-process: allocate `LVITEMW` + wchar buffer in Explorer with `VirtualAllocEx` / `WriteProcessMemory` / `ReadProcessMemory` / `VirtualFreeEx`. If text read fails, `name=""`.
- Resolve path: `desktop_roots()`; for each root, if `(root / name)` exists, use it. Prefer the file that `paths_equal` would match a future lock path.

Return `IconHit(path, name, x, y, w, h)` in **screen pixels**.

- [ ] **Step 2: Manual**: run a tiny `if __name__` print of icon names while desktop has a known file. Do not fail CI if Explorer layout cannot be read (return `[]`).

- [ ] **Step 3: Commit**

```bash
git add src/desktop_icons.py
git commit -m "feat: read desktop icon rects from Explorer"
```

---

### Task 9: Destroy session orchestrator

**Files:**
- Create: `src/destroy_session.py`
- Create: `tests/test_destroy_session.py`

- [ ] **Step 1: Implement `DestroySession`**

Constructor: `(pet: PetWindow, overlay: DestroyOverlay)`.

`begin(path: str) -> None`:

1. If file missing: overlay show, prompt `OVERLAY_GONE`, QTimer `OVERLAY_GONE_SEC` then close. No recycle.
2. Else save `self._locked = path`, `behavior.set_frozen(True)`, show overlay with `OVERLAY_PROMPT`.
3. Overlay `clicked(x,y)`: `icons = list_desktop_icons()`; `hit = hit_icon(icons, x, y)`.
   - Hit and `paths_equal(hit.path, locked)` **or** (`not hit.path` and `hit.name` equals locked file name): store `self._target_center = hit.center`, fade/hide overlay (`OVERLAY_FADE_MS`), `set_frozen(False)`, convert center to window top-left: `cx - pet.width()/2`, `cy - pet.height()/2`, `set_chase_target`, `start_destroy_chase()`.
   - Else: `shake()`, prompt `OVERLAY_WRONG`, timer restore `OVERLAY_PROMPT` after `OVERLAY_WRONG_SEC`.
4. Overlay cancelled: hide, `set_frozen(False)`, clear locked path.
5. Each pet tick (session hooked from `PetWindow._tick`): if waiting on arrive and `destroy_arrived()`: `begin_destroy_action()`. If `destroy_action_finished()`: `send_to_recycle_bin(locked)`; on failure, session sets a short subtitle on overlay or pet (reuse overlay 1.5s with error string, then hide). Clear state.
6. If `behavior.state == State.DRAG` while destroy chase/action pending: cancel, **do not** recycle.

Ignore extra `begin()` while a session is active (or replace: cancel previous then start new — pick **ignore** while active).

- [ ] **Step 2: Unit-test hit matching without Explorer**

```python
# tests/test_destroy_session.py
from src.destroy_session import click_matches_lock
from src.hit import IconHit


def test_match_by_path() -> None:
    hit = IconHit(r"C:\Users\a\Desktop\x.txt", "x.txt", 0, 0, 10, 10)
    assert click_matches_lock(hit, r"C:\Users\a\Desktop\x.txt") is True


def test_match_by_name_if_path_empty() -> None:
    hit = IconHit("", "x.txt", 0, 0, 10, 10)
    assert click_matches_lock(hit, r"C:\Users\a\Desktop\x.txt") is True


def test_wrong_icon() -> None:
    hit = IconHit(r"C:\Users\a\Desktop\y.txt", "y.txt", 0, 0, 10, 10)
    assert click_matches_lock(hit, r"C:\Users\a\Desktop\x.txt") is False


def test_miss_none() -> None:
    assert click_matches_lock(None, r"C:\Users\a\Desktop\x.txt") is False
```

```python
# in src/destroy_session.py
def click_matches_lock(hit: IconHit | None, locked_path: str) -> bool:
    if hit is None:
        return False
    if hit.path and paths_equal(hit.path, locked_path):
        return True
    if not hit.path and hit.name and hit.name.casefold() == Path(locked_path).name.casefold():
        return True
    return False
```

- [ ] **Step 3: Commit**

```bash
git add src/destroy_session.py tests/test_destroy_session.py
git commit -m "feat: destroy session orchestration"
```

---

### Task 10: Wire pet window + main

**Files:**
- Modify: `src/pet_window.py`
- Modify: `src/main.py`
- Modify: `tools/smoke_test.py`

- [ ] **Step 1: PetWindow**

Create `DestroyOverlay` and `DestroySession` in `__init__`. Expose `start_destroy(path: str)`.

In `_tick`, when `wants_chase_target()`: keep mouse chase. When `_move_kind == "destroy"`: **do not** overwrite target with cursor. Call `self._destroy_session.tick()` every frame.

`mousePressEvent`: if session is in chase/action phase, `notify_interaction` / drag still works (cancel). If overlay is visible, overlay sits on top so pet will not receive clicks.

- [ ] **Step 2: main.py**

```python
from .destroy_ipc import DestroyIpc
from .shell_register import register_shell_extension  # Task 12; stub until then

def main() -> int:
    instance = SingleInstance()
    if not instance.acquired:
        return 0
    import os
    if os.environ.get("NAIWA_SKIP_SHELL_REG") != "1":
        register_shell_extension()  # no-op stub returning None until Task 12
    app = QApplication(sys.argv)
    ...
    pet = PetWindow()
    ipc = DestroyIpc()
    ipc.path_received.connect(pet.start_destroy)
    ipc.start()
    pet.show()
    try:
        return app.exec()
    finally:
        ipc.stop()
        instance.close()
```

Until Task 12, `register_shell_extension` can live as empty function in `src/shell_register.py`:

```python
def register_shell_extension() -> None:
    return
```

- [ ] **Step 3: smoke_test.py**

Set `os.environ["NAIWA_SKIP_SHELL_REG"] = "1"` **before** importing `src.main` or constructing PetWindow via the same mutex-safe path. If smoke still constructs `PetWindow` directly, also create+close mutex only if you start IPC — current smoke does not need IPC. Keep smoke as direct `PetWindow` + quit; do **not** register COM.

- [ ] **Step 4: Run smoke**

Run: `.\.venv\Scripts\python.exe tools\smoke_test.py`

Expected: `smoke test ok, real_assets = True` (or False if assets missing), exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/pet_window.py src/main.py src/shell_register.py tools/smoke_test.py
git commit -m "feat: wire destroy IPC to pet window"
```

---

### Task 11: C# COM context menu

**Files:**
- Create: `shell/NaiwaShell/NaiwaShell.csproj`
- Create: `shell/NaiwaShell/NaiwaContextMenu.cs`
- Create: `shell/NaiwaShell/Native.cs`
- Create: `shell/NaiwaShell/register.ps1`
- Create: `shell/NaiwaShell/unregister.ps1`

- [ ] **Step 1: csproj**

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0-windows</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <EnableComHosting>true</EnableComHosting>
    <PlatformTarget>x64</PlatformTarget>
    <AssemblyName>NaiwaShell</AssemblyName>
  </PropertyGroup>
</Project>
```

- [ ] **Step 2: COM class**

`[ComVisible(true)]`, `[Guid("8F3C2A11-9B4E-4D6A-9C71-2E7A1B4C5D6E")]`, `[ClassInterface(ClassInterfaceType.None)]`.

Implement `IShellExtInit` + `IContextMenu` (IUnknown vtables; use `[PreserveSig]` where required).

`Initialize`: from `IDataObject` get `CF_HDROP`, `DragQueryFile` index **0 only**. Store that path.

`QueryContextMenu`: if mutex `Local\NaiwaPet.Running` cannot be opened → return `HRESULT` with 0 items (`idCmdFirst`). If path is not under user Desktop or Public Desktop (ordinal ignore-case prefix, after `GetFullPath`) → 0 items. Else `InsertMenu` one item `召唤奶蛙摧毁` at `idCmdFirst`, return 1.

`InvokeCommand`: `NamedPipeClientStream(".", "NaiwaDestroy", PipeDirection.Out)` `Connect(300)`, write UTF-8 path + `\n`, no MessageBox on failure.

- [ ] **Step 3: Build**

Run: `dotnet build shell\NaiwaShell\NaiwaShell.csproj -c Release`

Expected: `NaiwaShell.dll` and `NaiwaShell.comhost.dll` in `shell\NaiwaShell\bin\Release\net8.0-windows\`.

- [ ] **Step 4: register.ps1 / unregister.ps1**

`register.ps1`: copy `NaiwaShell.dll`, `NaiwaShell.comhost.dll`, and deps (`NaiwaShell.runtimeconfig.json`, `NaiwaShell.deps.json`, hostpolicy if needed — copy the whole output folder) to `$env:LOCALAPPDATA\Naiwa\shell\`. Then:

```powershell
regsvr32 /s /n /i:user "$env:LOCALAPPDATA\Naiwa\shell\NaiwaShell.comhost.dll"
```

Also set HKCU:

```
HKCU\Software\Classes\CLSID\{8F3C2A11-9B4E-4D6A-9C71-2E7A1B4C5D6E}\InprocServer32
  (default) = full path to NaiwaShell.comhost.dll
  ThreadingModel = Apartment

HKCU\Software\Classes\AllFilesystemObjects\shellex\ContextMenuHandlers\NaiwaDestroy
  (default) = {8F3C2A11-9B4E-4D6A-9C71-2E7A1B4C5D6E}
```

If `regsvr32` already writes CLSID, still write the ContextMenuHandlers key.

`unregister.ps1`: delete ContextMenuHandlers\NaiwaDestroy, `regsvr32 /s /u /n /i:user` the comhost, do not crash if missing.

After register, `SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0)` via a one-liner C# or Python ctypes.

- [ ] **Step 5: Manual**

Start Naiwa, right-click a desktop file. Classic menu or Shift+F10 / “Show more options” must list 召唤奶蛙摧毁. Quit Naiwa, right-click again: item gone. Do not recycle yet if overlay not ready; pipe connect may no-op.

- [ ] **Step 6: Commit**

```bash
git add shell/NaiwaShell
git commit -m "feat: COM context menu for desktop destroy"
```

---

### Task 12: Python COM register on launch

**Files:**
- Modify: `src/shell_register.py`
- Modify: `Naiwa.spec` only if you add datas for the shell output folder (copy `shell/NaiwaShell/bin/Release/net8.0-windows` → `NaiwaShell` next to assets). Prefer locating DLL via:

1. `%LOCALAPPDATA%\Naiwa\shell\NaiwaShell.comhost.dll` if present
2. Else repo `shell/NaiwaShell/bin/Release/net8.0-windows/NaiwaShell.comhost.dll`
3. Else skip (log warning)

- [ ] **Step 1: Implement `register_shell_extension()`**

If `NAIWA_SKIP_SHELL_REG=1`, return. Else copy files to LocalAppData (same as register.ps1), write HKCU ContextMenuHandlers + InprocServer32 with `winreg`, call `SHChangeNotify`. Do not require admin. Catch all exceptions and print to stderr; pet still runs.

- [ ] **Step 2: Naiwa.spec datas**

If the Release folder exists at pack time, add it:

```python
datas=[('assets', 'assets'), ('shell/NaiwaShell/bin/Release/net8.0-windows', 'NaiwaShell')],
```

`shell_register` should also look at `sys._MEIPASS / NaiwaShell` when frozen, then copy to LocalAppData (never point InprocServer32 at `_MEIPASS`).

- [ ] **Step 3: Commit**

```bash
git add src/shell_register.py Naiwa.spec
git commit -m "feat: register Naiwa shell extension on startup"
```

---

### Task 13: README + end-to-end check

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document**

- Need .NET 8 SDK to build `shell/NaiwaShell`
- `dotnet build shell\NaiwaShell\NaiwaShell.csproj -c Release`
- Run pet; first launch registers HKCU menu
- Unregister: `powershell -File shell\NaiwaShell\unregister.ps1`
- Dev: `NAIWA_SKIP_SHELL_REG=1` to skip
- Win11: use “Show more options” if the verb is not on the first pane
- Destroy animation currently reuses `laugh` frames

- [ ] **Step 2: Manual E2E**

1. `pytest tests -v` all green
2. `python tools/smoke_test.py` ok
3. Build COM, start pet, put a throwaway txt on desktop
4. Right-click → 召唤奶蛙摧毁 → overlay → click wrong icon → 不是这个
5. Click correct icon → pet crawls → laugh/destroy plays → file in Recycle Bin, restorable
6. Quit pet → menu item hidden
7. Esc cancels without delete
8. Shortcut: only `.lnk` recycled

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: desktop destroy usage and shell build"
```

---

## Self-review (spec coverage)

| Spec item | Task |
|---|---|
| Menu only while pet running (mutex) | 4, 11 |
| Desktop-only paths (user + public) | 1, 11 |
| Files, folders, shortcuts | 11 AllFilesystemObjects + recycle `.lnk` as given |
| Overlay ritual + click-through blocked | 7 |
| Wrong click reminds, Esc/right cancel | 7, 9 |
| Crawl to icon, then anim, then recycle | 6, 9 |
| Recycle Bin not `os.remove` | 3 |
| COM DLL not in PyInstaller temp | 11, 12 |
| No auto-start pet from menu | 11 Invoke pipe only |
| One item if multi-select | 11 index 0 |
| `destroy` uses laugh placeholder | 6 |
| Smoke skips COM | 10 |
| IExplorerCommand Win11 first pane | Explicitly out of spec v1 — not in plan |
| Drag during destroy cancels | 6, 9 |
| Missing file “已经没了” | 9 |
| Recycle failure after anim | 9 |
