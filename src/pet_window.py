"""桌宠主窗口：透明无边框、始终置顶，负责绘制、拖拽和右键菜单。"""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QAction, QCursor, QPainter, QTransform
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from . import config
from .drag import DragSway
from .behavior import Behavior, State
from .destroy_overlay import DestroyOverlay
from .destroy_session import DestroySession
from .paths import is_desktop_path
from .sprite import FrameBlender, SpriteLibrary


class PetWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()

        flags = Qt.FramelessWindowHint | Qt.Tool
        if config.ALWAYS_ON_TOP:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(config.APP_NAME)
        self.setCursor(Qt.OpenHandCursor)

        self.lib = SpriteLibrary()
        self._blender = FrameBlender()
        # 窗口按最大帧尺寸留白，放大后的走路帧也不会被裁切
        win_w, win_h = self.lib.bounding_size()
        self.resize(win_w, win_h)
        self.behavior = Behavior(self.lib)
        self._destroy_overlay = DestroyOverlay()
        self._destroy_session = DestroySession(self, self._destroy_overlay)
        self._apply_screen_bounds()

        # 拖拽状态：按下后先不算拖动，移动超过阈值才进入“拎起”
        self._pressing = False
        self._dragging = False
        self._press_global = QPoint()
        self._last_cursor_x: float | None = None
        self._sway = DragSway()
        self._tilt = 0.0

        # 把窗口放到屏幕底部靠左
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.left() + 40, screen.bottom() - self.height())
        # 爬行位置用浮点累加：一帧只走不到 1 像素，直接写回整数窗口坐标会被抹平
        self._pos_x = float(self.x())
        self._pos_y = float(self.y())

        self._last_t = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 / config.DISPLAY_FPS))

    # ---- 屏幕范围（跟随奶蛙当前所在屏幕，支持多显示器）----
    def _screen_for_pet(self):
        center = self.frameGeometry().center()
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen

    def _apply_screen_bounds(self) -> None:
        geo = self._screen_for_pet().availableGeometry()
        # 横向可走范围 = 所有与当前屏幕纵向重叠的屏幕的并集，这样能爬到隔壁显示器上；
        # 纵向仍按当前屏幕，免得爬到任务栏底下或没有画面的区域。
        span = geo
        for screen in QApplication.screens():
            other = screen.availableGeometry()
            if other.top() <= geo.bottom() and other.bottom() >= geo.top():
                span = span.united(other)
        self.behavior.set_bounds(
            span.left(), span.right() - self.width(),
            geo.top(), geo.bottom() - self.height(),
        )

    # ---- 主循环 ----
    def _tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_t
        self._last_t = now

        if self._dragging:
            self._update_drag_position(dt)
            self.behavior.anim.advance(dt)
        else:
            # 每帧按当前屏幕刷新边界，避免副屏散步时被夹回主屏
            self._apply_screen_bounds()
            # 追鼠标：趴下/爬行/站起过程都刷新目标
            if self.behavior.wants_chase_target():
                cursor = QCursor.pos()
                self.behavior.set_chase_target(
                    cursor.x() - self.width() / 2,
                    cursor.y() - self.height() / 2,
                )
            x, y = self.behavior.update(dt, self._pos_x, self._pos_y)
            if (x, y) != (self._pos_x, self._pos_y):
                self._pos_x, self._pos_y = x, y
                self.move(round(x), round(y))
            # 拖拽结束后倾斜平滑回正
            self._tilt = self._sway.advance(dt)

        self._destroy_session.tick()
        self.update()

    def start_destroy(self, path: str) -> None:
        """接受 Shell 扩展传来的目标；主进程再次限制为桌面文件系统路径。"""
        if not path or not is_desktop_path(path):
            return
        self._destroy_session.begin(path)

    def destroy_target(self, center_x: int, center_y: int) -> tuple[float, float, bool]:
        """把图标位置对齐到坐下时的屁股，而非透明窗口中心。"""
        facing = center_x >= self.x() + self.width() / 2
        frame = self.lib.make("destroy_slam").current
        ax, ay = self.lib.destroy_anchor()
        offset_x = (ax - 0.5) * frame.width()
        if not facing:
            offset_x = -offset_x
        return (center_x - self.width() / 2 - offset_x,
                center_y - self.height() / 2 - (ay - 0.5) * frame.height(), facing)

    def _start_menu_action(self, action: str) -> None:
        self._destroy_session.cancel()
        self.behavior.start_action(action)

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        anim = self.behavior.anim
        pm = anim.current
        painter = QPainter(self)
        # 帧已预缩放到显示尺寸，用 Fast 变换降低每帧开销，提升观感帧率
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.setRenderHint(QPainter.Antialiasing, False)

        painter.setRenderHint(QPainter.SmoothPixmapTransform, bool(self._tilt))
        painter.setTransform(self._frame_transform(pm))
        spec = config.ACTIONS.get(anim.action)
        self._draw_frame(painter, anim, pm, spec)
        painter.end()

    def _grip(self, pm) -> QPointF:
        return QPointF(pm.width() * config.DRAG_GRIP[0],
                       pm.height() * config.DRAG_GRIP[1])

    def _frame_transform(self, pm) -> QTransform:
        spec = config.ACTIONS.get(self.behavior.anim.action)
        mirrored = self.behavior.facing_right != (True if spec is None else spec.faces_right)
        anchor = self._grip(pm) if self._dragging else QPointF(pm.width() / 2, pm.height() / 2)
        # 抓取点既是鼠标锚点也是旋转轴，镜像不改变旋转方向。
        origin = QPointF(self.width() / 2, self.height() / 2)
        if self._dragging:
            origin += QPointF((pm.width() / 2 - anchor.x()) if mirrored else
                              (anchor.x() - pm.width() / 2), anchor.y() - pm.height() / 2)
        t = QTransform()
        t.translate(origin.x(), origin.y())
        t.rotate(self._tilt)
        if mirrored:
            t.scale(-1, 1)
        t.translate(-anchor.x(), -anchor.y())
        return t

    def _draw_frame(self, painter: QPainter, anim, pm, spec) -> None:
        """画当前帧；素材帧率低于屏幕刷新率时和下一帧插值，避免快动作一顿一顿。"""
        blend_fps = spec.fps if spec is not None else config.DISPLAY_FPS
        nxt = anim.upcoming
        phase = anim.phase
        if (not config.FRAME_BLEND
                or blend_fps >= config.FRAME_BLEND_MIN_FPS
                or nxt is pm
                or nxt.size() != pm.size()
                or phase <= 0.01):
            painter.drawPixmap(0, 0, pm)
            return

        dx, dy = anim.blend_shift
        painter.drawImage(0, 0, self._blender.blend(pm, nxt, phase, dx, dy))

    # ---- 鼠标交互 ----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.behavior.notify_interaction()
            self._pressing = True
            self._dragging = False
            self.setCursor(Qt.ClosedHandCursor)
            self._press_global = event.globalPosition().toPoint()
            self._last_cursor_x = float(self._press_global.x())
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._pressing:
            return
        pos = event.globalPosition().toPoint()
        if not self._dragging:
            dx = pos.x() - self._press_global.x()
            dy = pos.y() - self._press_global.y()
            if dx * dx + dy * dy < config.DRAG_THRESHOLD_PX ** 2:
                return
            # 真正开始拖动才切到拎起姿势（光标在按下时已是握住）
            self._dragging = True
            self.behavior.start_drag()
            self._sway = DragSway()
            self._tilt = 0.0
            self._last_cursor_x = float(pos.x())
            self._last_t = time.monotonic()

        self._place_grip_at(pos)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or not self._pressing:
            return
        was_dragging = self._dragging
        if was_dragging:
            self._place_grip_at(event.globalPosition().toPoint())
            pm = self.behavior.anim.current
            center = self._frame_transform(pm).map(QPointF(pm.width() / 2, pm.height() / 2))
            center += QPointF(self.pos())
        self._pressing = False
        self._dragging = False
        self._last_cursor_x = None
        self.setCursor(Qt.OpenHandCursor)
        if was_dragging:
            self.behavior.end_drag()
            # 旋转轴切回身体中心时补偿窗口位置，避免松手瞬移。
            self.move(round(center.x() - self.width() / 2), round(center.y() - self.height() / 2))
            self._pos_x, self._pos_y = float(self.x()), float(self.y())
            self._sway.cursor_velocity = 0.0
            self._apply_screen_bounds()
        self.update()
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.behavior.notify_interaction()
        menu = QMenu(self)
        for label, action in config.MENU_ACTIONS:
            act = QAction(label, self)
            act.triggered.connect(lambda _=False, a=action: self._start_menu_action(a))
            menu.addAction(act)
        menu.addSeparator()
        quit_act = QAction("退出", self)
        quit_act.triggered.connect(QApplication.quit)
        menu.addAction(quit_act)
        menu.exec(event.globalPos())

    # ---- 拖拽辅助 ----
    def _place_grip_at(self, pos: QPoint) -> None:
        pm = self.behavior.anim.current
        local = self._frame_transform(pm).map(self._grip(pm))
        self.move(round(pos.x() - local.x()), round(pos.y() - local.y()))
        self._pos_x, self._pos_y = float(self.x()), float(self.y())

    def _update_drag_position(self, dt: float) -> None:
        pos = QCursor.pos()
        dx = 0.0 if self._last_cursor_x is None else pos.x() - self._last_cursor_x
        self._last_cursor_x = float(pos.x())
        self._tilt = self._sway.advance(dt, dx)
        self._place_grip_at(pos)
