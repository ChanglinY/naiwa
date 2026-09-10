import math
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from src.drag import DragSway
from src import config
from src.pet_window import PetWindow


def test_direction_reverse_and_settle():
    sway = DragSway()
    for _ in range(60):
        sway.advance(1 / 60, 5)
    assert sway.angle > 5
    for _ in range(60):
        sway.advance(1 / 60, -5)
    assert sway.angle < -5
    for _ in range(240):
        sway.advance(1 / 60)
    assert abs(sway.angle) < .01
    assert abs(sway.velocity) < .01


def test_frame_rate_and_long_pause():
    angles = []
    for fps in (30, 60, 144):
        sway = DragSway()
        for _ in range(fps):
            sway.advance(1 / fps, 300 / fps)
        angles.append(sway.angle)
        for _ in range(20):
            assert abs(sway.advance(10, 100000)) <= config.DRAG_MAX_TILT
            assert math.isfinite(sway.velocity)
    assert max(angles) - min(angles) < .2


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        pytest.skip("IPC tests created QCoreApplication; run test_drag.py separately for QWidget checks")
    return existing or QApplication([])


def send_mouse(pet, kind, global_pos, button, buttons):
    local = global_pos - QPointF(pet.pos())
    event = QMouseEvent(kind, local, global_pos, button, buttons, Qt.NoModifier)
    QApplication.sendEvent(pet, event)


@pytest.mark.parametrize("facing", [True, False])
def test_drag_events_anchor_release_and_render(app, facing):
    pet = PetWindow()
    pet._timer.stop()
    pet.behavior.facing_right = facing
    pet.show()
    app.processEvents()
    start = QPointF(pet.pos()) + QPointF(100, 120)
    send_mouse(pet, QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
    send_mouse(pet, QEvent.MouseMove, start + QPointF(2, 1), Qt.NoButton, Qt.LeftButton)
    assert not pet._dragging
    cursor = start + QPointF(90, 30)
    send_mouse(pet, QEvent.MouseMove, cursor, Qt.NoButton, Qt.LeftButton)
    assert pet._dragging
    pm = pet.behavior.anim.current
    for angle in (-22, 0, 22):
        pet._tilt = angle
        pet._place_grip_at(cursor.toPoint())
        transform = pet._frame_transform(pm)
        grip = transform.map(pet._grip(pm)) + QPointF(pet.pos())
        assert abs(grip.x() - cursor.x()) <= .5
        assert abs(grip.y() - cursor.y()) <= .5
        # 所有可见像素在窗口内，透明画布角落不参与裁切断言。
        im = pm.toImage()
        for y in range(im.height()):
            for x in range(im.width()):
                if im.pixelColor(x, y).alpha() > 32:
                    point = transform.map(QPointF(x, y))
                    assert 0 <= point.x() < pet.width()
                    assert 0 <= point.y() < pet.height()
        assert not pet.grab().isNull()
    center = pet._frame_transform(pm).map(QPointF(pm.width()/2, pm.height()/2)) + QPointF(pet.pos())
    send_mouse(pet, QEvent.MouseButtonRelease, cursor, Qt.LeftButton, Qt.NoButton)
    assert not pet._dragging
    assert pet.behavior.anim.action != "drag"
    after = QPointF(pet.pos()) + QPointF(pet.width()/2, pet.height()/2)
    assert abs(center.x() - after.x()) <= .5
    assert abs(center.y() - after.y()) <= .5
    # 连续再抓一次应重置惯性，而且重新锁定尖端。
    send_mouse(pet, QEvent.MouseButtonPress, cursor, Qt.LeftButton, Qt.LeftButton)
    send_mouse(pet, QEvent.MouseMove, cursor + QPointF(-40, 0), Qt.NoButton, Qt.LeftButton)
    assert pet._sway.angle == 0
    assert pet._dragging
    pet.close()
