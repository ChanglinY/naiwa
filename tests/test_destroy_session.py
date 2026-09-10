from __future__ import annotations

from dataclasses import dataclass

import src.destroy_session as session_module
from src.behavior import State
from src.destroy_session import DestroyPhase, DestroySession, click_matches_lock


@dataclass
class _Icon:
    path: str
    name: str
    x: int = 10
    y: int = 20
    w: int = 30
    h: int = 40

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback

    def emit(self, *args) -> None:
        assert self.callback is not None
        self.callback(*args)


class _Overlay:
    def __init__(self) -> None:
        self.clicked = _Signal()
        self.cancelled = _Signal()
        self.prompt = ""
        self.visible = False
        self.shakes = 0

    def show_overlay(self, prompt: str) -> None:
        self.prompt = prompt
        self.visible = True

    def set_prompt(self, prompt: str) -> None:
        self.prompt = prompt

    def shake(self) -> None:
        self.shakes += 1

    def fade_out(self, callback) -> None:
        self.visible = False
        callback()

    def hide(self) -> None:
        self.visible = False


class _Behavior:
    def __init__(self) -> None:
        self.state = State.IDLE
        self.frozen = False
        self.target = None
        self.chases = 0
        self.impact = False
        self.finished = False

    def set_frozen(self, value: bool) -> None:
        self.frozen = value

    def set_chase_target(self, x: float, y: float) -> None:
        self.target = (x, y)

    def start_destroy_chase(self, facing_right=None) -> None:
        self.chases += 1

    def cancel_destroy_action(self) -> None:
        self.impact = False
        self.finished = False

    def destroy_impact(self) -> bool:
        result, self.impact = self.impact, False
        return result

    def destroy_arrived(self) -> bool:
        return False

    def destroy_action_finished(self) -> bool:
        result, self.finished = self.finished, False
        return result


class _Pet:
    def __init__(self) -> None:
        self.behavior = _Behavior()

    def width(self) -> int:
        return 100

    def height(self) -> int:
        return 80

    def destroy_target(self, x, y):
        return x - self.width() / 2, y - self.height() / 2, True


def test_click_match_by_path_and_name_fallback(tmp_path) -> None:
    locked = tmp_path / "x.txt"
    locked.write_text("x", encoding="utf-8")

    assert click_matches_lock(_Icon(str(locked), "x.txt"), str(locked))
    assert click_matches_lock(_Icon("", "X.TXT"), str(locked))
    assert not click_matches_lock(_Icon("", "y.txt"), str(locked))
    assert not click_matches_lock(None, str(locked))


def test_correct_click_starts_fixed_target_chase(monkeypatch, tmp_path) -> None:
    locked = tmp_path / "x.txt"
    locked.write_text("x", encoding="utf-8")
    icon = _Icon(str(locked), "x.txt")
    monkeypatch.setattr(session_module, "list_desktop_icons", lambda: [icon])
    pet = _Pet()
    overlay = _Overlay()
    session = DestroySession(pet, overlay)

    session.begin(str(locked))
    overlay.clicked.emit(15, 25)

    assert session.phase is DestroyPhase.CHASING
    assert pet.behavior.frozen is False
    assert pet.behavior.target == (-25.0, 0.0)
    assert pet.behavior.chases == 1


def test_wrong_click_keeps_confirmation_open(monkeypatch, tmp_path) -> None:
    locked = tmp_path / "x.txt"
    locked.write_text("x", encoding="utf-8")
    monkeypatch.setattr(session_module, "list_desktop_icons", lambda: [])
    overlay = _Overlay()
    session = DestroySession(_Pet(), overlay)

    session.begin(str(locked))
    overlay.clicked.emit(0, 0)

    assert session.phase is DestroyPhase.CONFIRMING
    assert overlay.prompt == "不是这个"
    assert overlay.shakes == 1


def test_drag_cancels_chase_without_recycle(tmp_path) -> None:
    locked = tmp_path / "x.txt"
    locked.write_text("x", encoding="utf-8")
    pet = _Pet()
    overlay = _Overlay()
    session = DestroySession(pet, overlay)
    session.begin(str(locked))
    session.phase = DestroyPhase.CHASING
    pet.behavior.state = State.DRAG

    session.tick()

    assert session.active is False
    assert locked.exists()


def test_recycle_at_impact_once_and_keep_tail_playing(monkeypatch, tmp_path) -> None:
    import src.recycle as recycle
    locked = tmp_path / "x.txt"
    locked.write_text("x", encoding="utf-8")
    calls = []
    monkeypatch.setattr(recycle, "send_to_recycle_bin", lambda p: (calls.append(p) or True, ""))
    pet = _Pet()
    session = DestroySession(pet, _Overlay())
    session.begin(str(locked))
    session.phase = DestroyPhase.ANIMATING
    session.tick()
    assert calls == []
    pet.behavior.impact = True
    session.tick()
    assert calls == [str(locked)]
    assert session.phase is DestroyPhase.ANIMATING
    pet.behavior.impact = True  # Duplicate notification must still be harmless.
    session.tick()
    assert len(calls) == 1
    pet.behavior.finished = True
    session.tick()
    assert not session.active
    assert len(calls) == 1


def test_failed_recycle_is_not_retried_after_tail(monkeypatch, tmp_path) -> None:
    import src.recycle as recycle
    locked = tmp_path / "x.txt"
    locked.write_text("x", encoding="utf-8")
    calls = []
    monkeypatch.setattr(recycle, "send_to_recycle_bin", lambda p: (calls.append(p) and False, "access denied"))
    pet = _Pet()
    overlay = _Overlay()
    session = DestroySession(pet, overlay)
    session.begin(str(locked))
    session.phase = DestroyPhase.ANIMATING
    pet.behavior.impact = True
    session.tick()
    assert session.phase is DestroyPhase.ANIMATING
    pet.behavior.finished = True
    session.tick()
    assert session.phase is DestroyPhase.FEEDBACK
    assert "access denied" in overlay.prompt
    assert calls == [str(locked)]
    assert locked.exists()
