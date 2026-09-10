"""摧毁仪式会话：确认图标、追逐、动画完成后回收。"""

from __future__ import annotations

import os
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import QTimer

from . import config
from .behavior import State
from .desktop_icons import list_desktop_icons


class DestroyPhase(Enum):
    IDLE = auto()
    CONFIRMING = auto()
    CHASING = auto()
    ANIMATING = auto()
    FEEDBACK = auto()


def _paths_equal(a: str, b: str) -> bool:
    try:
        from .paths import paths_equal

        return paths_equal(a, b)
    except ImportError:
        return os.path.normcase(os.path.abspath(a).rstrip("\\/")) == os.path.normcase(
            os.path.abspath(b).rstrip("\\/")
        )


def click_matches_lock(hit, locked_path: str) -> bool:
    """命中路径优先；读取不到路径时才按不区分大小写的文件名兜底。"""
    if hit is None:
        return False
    if hit.path and _paths_equal(hit.path, locked_path):
        return True
    return bool(
        not hit.path
        and hit.name
        and hit.name.casefold() == Path(locked_path).name.casefold()
    )


def _hit_icon(icons: list, x: int, y: int):
    try:
        from .hit import hit_icon

        return hit_icon(icons, x, y)
    except ImportError:
        return next((icon for icon in icons if icon.contains(x, y)), None)


class DestroySession:
    def __init__(self, pet, overlay) -> None:
        self.pet = pet
        self.overlay = overlay
        self.phase = DestroyPhase.IDLE
        self._locked = ""
        self._generation = 0
        self._recycle_attempted = False
        self._recycle_error = ""
        overlay.clicked.connect(self._on_clicked)
        overlay.cancelled.connect(self.cancel)

    @property
    def active(self) -> bool:
        return self.phase is not DestroyPhase.IDLE

    @property
    def locked_path(self) -> str:
        return self._locked

    def begin(self, path: str) -> None:
        if self.active:
            return
        self._generation += 1
        self._locked = path
        self._recycle_attempted = False
        self._recycle_error = ""
        self.pet.behavior.set_frozen(True)
        self.phase = DestroyPhase.CONFIRMING

        if not os.path.exists(path):
            self.overlay.show_overlay(config.OVERLAY_GONE)
            self._later(config.OVERLAY_GONE_SEC, self._finish)
            return
        self.overlay.show_overlay(config.OVERLAY_PROMPT)

    def cancel(self) -> None:
        if not self.active:
            return
        self._generation += 1
        self.overlay.hide()
        self.pet.behavior.set_frozen(False)
        self.pet.behavior.cancel_destroy_action()
        self.phase = DestroyPhase.IDLE
        self._locked = ""

    def _on_clicked(self, x: int, y: int) -> None:
        if self.phase is not DestroyPhase.CONFIRMING:
            return
        hit = _hit_icon(list_desktop_icons(), x, y)
        if not click_matches_lock(hit, self._locked):
            # 使更早一次错误点击的恢复定时器失效；每次点击都完整显示 1.2 秒。
            self._generation += 1
            self.overlay.set_prompt(config.OVERLAY_WRONG)
            self.overlay.shake()
            generation = self._generation
            QTimer.singleShot(
                round(config.OVERLAY_WRONG_SEC * 1000),
                lambda: self._restore_prompt(generation),
            )
            return

        center_x, center_y = hit.center
        self.phase = DestroyPhase.CHASING
        generation = self._generation
        self.overlay.fade_out(
            lambda: self._start_chase(generation, center_x, center_y)
        )

    def _restore_prompt(self, generation: int) -> None:
        if generation == self._generation and self.phase is DestroyPhase.CONFIRMING:
            self.overlay.set_prompt(config.OVERLAY_PROMPT)

    def _start_chase(self, generation: int, center_x: int, center_y: int) -> None:
        if generation != self._generation or self.phase is not DestroyPhase.CHASING:
            return
        behavior = self.pet.behavior
        behavior.set_frozen(False)
        target_x, target_y, facing = self.pet.destroy_target(center_x, center_y)
        behavior.set_chase_target(target_x, target_y)
        behavior.start_destroy_chase(facing_right=facing)

    def tick(self) -> None:
        """由宠物窗口每帧调用，消费行为状态机的一次性事件。"""
        if self.phase in (DestroyPhase.CHASING, DestroyPhase.ANIMATING):
            if self.pet.behavior.state is State.DRAG:
                self.cancel()
                return

        if self.phase is DestroyPhase.CHASING:
            if self.pet.behavior.destroy_arrived():
                self.phase = DestroyPhase.ANIMATING
                self.pet.behavior.begin_destroy_action()
            return

        if self.phase is DestroyPhase.ANIMATING:
            if self.pet.behavior.destroy_impact() and not self._recycle_attempted:
                self._recycle()
            if self.pet.behavior.destroy_action_finished():
                if self._recycle_error:
                    self.phase = DestroyPhase.FEEDBACK
                    self.overlay.show_overlay(f"摧毁失败：{self._recycle_error}")
                    self._later(2.5, self._finish)
                else:
                    self._finish()

    def _recycle(self) -> None:
        # 先标记再调用系统 API，后续帧/收尾动作不可重复删除。
        self._recycle_attempted = True
        try:
            from .recycle import send_to_recycle_bin

            ok, error = send_to_recycle_bin(self._locked)
        except Exception as exc:
            ok, error = False, str(exc)

        if ok:
            return
        self._recycle_error = error.strip() or "无法移入回收站"

    def _later(self, seconds: float, callback) -> None:
        generation = self._generation
        QTimer.singleShot(
            round(seconds * 1000),
            lambda: callback() if generation == self._generation else None,
        )

    def _finish(self) -> None:
        if not self.active:
            return
        self._generation += 1
        self.overlay.hide()
        self.pet.behavior.set_frozen(False)
        self.phase = DestroyPhase.IDLE
        self._locked = ""
