"""程序入口：启动 Qt 应用与桌宠窗口。

运行:
    python -m src.main
或打包后直接双击生成的 exe。
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from . import config
from .destroy_ipc import DestroyIpc
from .pet_window import PetWindow
from .shell_register import register_shell_extension
from .single_instance import SingleInstance


def main() -> int:
    instance = SingleInstance()
    if not instance.acquired:
        return 0

    register_shell_extension()
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setQuitOnLastWindowClosed(True)

    pet = PetWindow()
    ipc = DestroyIpc(app)
    ipc.path_received.connect(pet.start_destroy, Qt.QueuedConnection)
    ipc.start()
    pet.show()

    try:
        return app.exec()
    finally:
        ipc.stop()
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
