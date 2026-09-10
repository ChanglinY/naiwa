"""桌面摧毁确认用的全虚拟桌面覆盖层。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import config


class DestroyOverlay(QWidget):
    confirmed = Signal()
    cancelled = Signal()
    wrong_click = Signal()
    clicked = Signal(int, int)

    def __init__(self, avatar: QPixmap | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._prompt = config.OVERLAY_PROMPT
        self._avatar = avatar or self._default_avatar()
        self._background_cache: dict[tuple[int, int], QPixmap] = {}
        self._shake_x = 0.0
        self._shake_anim: QPropertyAnimation | None = None
        self._fade_anim: QPropertyAnimation | None = None
        self._fade_callback: Callable[[], None] | None = None

    @staticmethod
    def _default_avatar() -> QPixmap:
        try:
            from .sprite import SpriteLibrary, _assets_root

            background = QPixmap(str(_assets_root() / "destroy_overlay.png"))
            if not background.isNull():
                return background

            return SpriteLibrary().make("idle_belly").current
        except Exception:
            return QPixmap()

    def set_avatar(self, avatar: QPixmap) -> None:
        self._avatar = avatar
        self._background_cache.clear()
        self.update()

    def set_prompt(self, text: str) -> None:
        self._prompt = text
        self.update()

    def show_overlay(self, prompt: str | None = None) -> None:
        if prompt is not None:
            self._prompt = prompt
        geometry = QRect()
        for screen in QApplication.screens():
            geometry = geometry.united(screen.geometry())
        if geometry.isNull() and QApplication.primaryScreen() is not None:
            geometry = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(geometry)
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)
        self.update()

    def fade_out(self, on_finished: Callable[[], None] | None = None) -> None:
        self._fade_callback = on_finished
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(config.OVERLAY_FADE_MS)
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade_anim.finished.connect(self._finish_fade)
        self._fade_anim.start()

    def _finish_fade(self) -> None:
        callback = self._fade_callback
        self._fade_callback = None
        self.hide()
        self.setWindowOpacity(1.0)
        self.confirmed.emit()
        if callback is not None:
            callback()

    def shake(self) -> None:
        self._shake_anim = QPropertyAnimation(self, b"shakeX", self)
        self._shake_anim.setDuration(200)
        self._shake_anim.setKeyValueAt(0.0, 0.0)
        self._shake_anim.setKeyValueAt(0.2, -14.0)
        self._shake_anim.setKeyValueAt(0.4, 12.0)
        self._shake_anim.setKeyValueAt(0.6, -8.0)
        self._shake_anim.setKeyValueAt(0.8, 5.0)
        self._shake_anim.setKeyValueAt(1.0, 0.0)
        self._shake_anim.start()
        self.wrong_click.emit()

    def _get_shake_x(self) -> float:
        return self._shake_x

    def _set_shake_x(self, value: float) -> None:
        self._shake_x = value
        self.update()

    shakeX = Property(float, _get_shake_x, _set_shake_x)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(40, 28, 22, 108))

        font = QFont()
        font.setPixelSize(22)
        font.setBold(True)
        painter.setFont(font)
        # 每个显示器独立铺满，避免双屏拼成长画幅后把角色裁掉或切在屏幕接缝上。
        regions = [s.geometry().translated(-self.x(), -self.y()).intersected(self.rect())
                   for s in QApplication.screens()]
        regions = [r for r in regions if not r.isEmpty()] or [self.rect()]
        for region in regions:
            painter.save()
            painter.setClipRect(region)
            if not self._avatar.isNull():
                key = (region.width(), region.height())
                if key not in self._background_cache:
                    self._background_cache[key] = self._avatar.scaled(
                        region.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                    )
                background = self._background_cache[key]
                x = region.x() + (region.width() - background.width()) // 2
                y = region.y() + (region.height() - background.height()) // 2
                painter.setOpacity(0.28)
                painter.drawPixmap(x + round(self._shake_x), y, background)
            painter.setOpacity(1.0)
            text_rect = QRect(region.x() + round(self._shake_x),
                              region.y() + round(region.height() * 0.82),
                              region.width(), max(70, round(region.height() * 0.16)))
            # 轻微文字阴影保证半透明背景上的提示仍可读。
            painter.setPen(QColor(30, 24, 18, 190))
            painter.drawText(text_rect.translated(0, 2), Qt.AlignHCenter | Qt.AlignTop, self._prompt)
            painter.setPen(QColor(255, 250, 244))
            painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, self._prompt)
            painter.restore()
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            point = event.globalPosition().toPoint()
            self.clicked.emit(point.x(), point.y())
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self.cancelled.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)
