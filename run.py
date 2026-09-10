"""顶层入口，供直接运行与 PyInstaller 打包使用。"""

from src.main import main

if __name__ == "__main__":
    raise SystemExit(main())
