"""Exercise real Qt confirmation, asset playback, placement and optional recycling.

Only the fresh temporary desktop file created by this script can be recycled.
python tools/verify_destroy_flow.py --real-recycle
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PIL import Image, ImageDraw

from src import config, recycle
from src.desktop_icons import list_desktop_icons
from src.destroy_session import DestroyPhase
from src.paths import desktop_roots, paths_equal
from src.pet_window import PetWindow


def main(real_recycle: bool) -> int:
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    pet = PetWindow()
    pet.show()
    root = desktop_roots()[0]
    with tempfile.NamedTemporaryFile(prefix="Naiwa-animation-test-", suffix=".txt", dir=root,
                                     delete=False) as file:
        target = Path(file.name)
        file.write(b"Disposable Naiwa animation integration test.\n")
    assert target.resolve().parent == root.resolve()
    session = pet._destroy_session
    original_recycle = recycle.send_to_recycle_bin
    result = {"real_recycle": real_recycle, "actions": [], "recycle_calls": 0}
    frames = []
    started = time.monotonic()
    last_capture = 0.0
    impact_exists = None

    def recycle_test(path):
        nonlocal impact_exists
        assert paths_equal(path, target), "Refusing to recycle anything except the fixture"
        assert pet.behavior.anim.action == "destroy_rise"
        assert pet.behavior.anim._index == 0
        assert target.exists()
        result["recycle_calls"] += 1
        result["recycle_at_action"] = pet.behavior.anim.action
        result["recycle_at_frame"] = pet.behavior.anim._index
        frame = pet.behavior.lib.make("destroy_slam").current
        ax, ay = pet.lib.destroy_anchor()
        contact = pet._frame_transform(frame).map(QPointF(ax * frame.width(), ay * frame.height()))
        contact += QPointF(pet.pos())
        result["contact_error_px"] = [contact.x() - icon.center[0], contact.y() - icon.center[1]]
        assert max(map(abs, result["contact_error_px"])) <= 1.0
        outcome = original_recycle(path) if real_recycle else (True, "")
        impact_exists = target.exists()
        assert outcome[0], outcome[1]
        if real_recycle:
            assert not impact_exists
        return outcome

    recycle.send_to_recycle_bin = recycle_test
    failure = []
    icon = None

    def fail(exc):
        failure.append(repr(exc))
        app.quit()

    def begin():
        nonlocal icon
        try:
            icon = next((i for i in list_desktop_icons() if i.path and paths_equal(i.path, target)), None)
            if icon is None:
                if time.monotonic() - started > 10:
                    raise AssertionError("Explorer did not show fixture icon")
                QTimer.singleShot(200, begin)
                return
            pet.start_destroy(str(target))
            assert session.phase is DestroyPhase.CONFIRMING
            QTest.mouseClick(pet._destroy_overlay, Qt.LeftButton, pos=QPoint(1400, 900))
            assert session.phase is DestroyPhase.CONFIRMING and target.exists()
            assert pet._destroy_overlay._prompt == config.OVERLAY_WRONG
            point = pet._destroy_overlay.mapFromGlobal(QPoint(*icon.center))
            QTest.mouseClick(pet._destroy_overlay, Qt.LeftButton, pos=point)
            assert session.phase is DestroyPhase.CHASING
            result["wrong_then_correct_click"] = True
        except Exception as exc:
            fail(exc)

    def observe():
        nonlocal last_capture
        try:
            elapsed = time.monotonic() - started
            if elapsed > 95:
                raise AssertionError("Destroy flow timed out")
            action = pet.behavior.anim.action
            if session.phase is DestroyPhase.ANIMATING:
                if not result["actions"] or result["actions"][-1] != action:
                    result["actions"].append(action)
                    print("Action:", action, flush=True)
                if not result["recycle_calls"]:
                    assert target.exists(), "File disappeared before second clip finished"
                if elapsed - last_capture > 0.12:
                    last_capture = elapsed
                    pm = QPixmap(pet.size())
                    pm.fill(Qt.transparent)
                    pet.render(pm)
                    qimage = pm.toImage().convertToFormat(__import__('PySide6.QtGui', fromlist=['QImage']).QImage.Format_RGBA8888)
                    image = Image.frombytes("RGBA", (qimage.width(), qimage.height()), bytes(qimage.bits()))
                    bg = Image.new("RGBA", (pet.width(), pet.height() + 28), (238, 236, 229, 255))
                    draw = ImageDraw.Draw(bg)
                    if not result["recycle_calls"]:
                        cx, cy = icon.center[0] - pet.x(), icon.center[1] - pet.y()
                        draw.rounded_rectangle((cx-14, cy-20, cx+14, cy+20), radius=3,
                                               fill=(250, 250, 255), outline=(85, 118, 183), width=2)
                    bg.alpha_composite(image)
                    draw.text((8, pet.height()+6), action, fill=(45,45,45))
                    frames.append(bg.convert("RGB"))
            if result["actions"] and not session.active:
                assert result["actions"] == list(config.DESTROY_SEQUENCE)
                assert result["recycle_calls"] == 1
                assert pet.behavior.state.name == "IDLE"
                result["completed"] = True
                result["elapsed_seconds"] = round(elapsed, 2)
                app.quit()
        except Exception as exc:
            fail(exc)

    observer = QTimer()
    observer.timeout.connect(observe)
    observer.start(15)
    QTimer.singleShot(300, begin)
    try:
        app.exec()
        if failure:
            raise AssertionError(failure)
        assert result.get("completed")
        (ROOT / "build/destroy-flow-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if frames:
            frames[0].save(ROOT / "build/destroy-flow.gif", save_all=True, append_images=frames[1:],
                           duration=125, loop=0)
        print(json.dumps(result, indent=2), flush=True)
    finally:
        observer.stop()
        pet._timer.stop()
        session.cancel()
        pet.close()
        recycle.send_to_recycle_bin = original_recycle
        # Exact temporary file created above; never remove any user-selected file.
        if target.exists():
            target.unlink()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-recycle", action="store_true")
    raise SystemExit(main(parser.parse_args().real_recycle))
