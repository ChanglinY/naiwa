"""启动桌宠并在数秒后自动退出，用于验证框架能正常运行。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config          # noqa: E402
from src.pet_window import PetWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    pet = PetWindow()
    pet.show()

    # 模拟触发一次互动，验证状态切换
    QTimer.singleShot(800, lambda: pet.behavior.start_action("laugh"))
    QTimer.singleShot(3000, app.quit)
    code = app.exec()
    print("smoke test ok, real_assets =", pet.lib.any_real_assets())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
