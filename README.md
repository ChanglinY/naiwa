# 奶蛙 (Naiwa)

Windows 桌面宠物：透明置顶、自动发呆/散步、可拖动、右键互动，并支持召唤奶蛙把桌面项目送进回收站。
基于 `fubao` 桌宠框架复用；动作素材放在 `assets/`，缺帧时会自动显示占位图。

## 快速交接

- 项目路径：`F:\naiwa`；用中文对话。
- 技术栈：Python 3.14 + PySide6，虚拟环境在 `.venv`。
- 运行：先建环境，再 `.\.venv\Scripts\python.exe run.py`
- 打包：`build.bat`（需要 .NET 8 SDK + PyInstaller，单个 exe → `dist\Naiwa.exe`）。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

### 已实现功能（框架）

- 透明无边框、始终置顶；不操作时自动发呆/散步（走到屏幕边缘掉头），支持多显示器。
- 左键拖动（拎起来会随手速晃动、松手回正）；只有真正拖动才切「被拎起」姿势。
- 右键菜单：玩耍 / 洗澡 / 吃饭 / 睡觉 / 退出。
- 睡觉随机两种姿势、会一直睡到被打断；待机时随机播舔手 / 打哈欠。
- 走路：素材朝向由 `config.py` 的 `faces_right` 控制，方向不一致时自动镜像。
- 帧间插值：素材 24fps、屏幕 60Hz，播放时按进度把相邻两帧对齐后混合，
  站起/趴下这类大位移不会一顿一顿（`config.FRAME_BLEND` 可关）。
- 桌面项目右键「召唤奶蛙摧毁」：全屏确认、点错提醒、跑位和动画后送进回收站。

### 素材现状

- 动作目录已建好，**尚未放入奶蛙素材**（缺帧时用占位图）。
- 需要准备：`idle` / `walk` / `drag` / `lick` / `yawn` / `play` / `bath` / `eat` / `sleep_curl` / `sleep_back`。

## 目录结构

```
naiwa/
├── run.py                 打包/运行入口
├── src/
│   ├── config.py          配置：动作、帧率、窗口、行为参数（改这里最多）
│   ├── sprite.py          序列帧加载与播放（缺素材时生成占位帧）
│   ├── behavior.py        行为状态机（发呆/散步/拖拽/互动）
│   ├── pet_window.py      透明置顶窗口 + 拖拽 + 右键菜单
│   └── main.py            应用启动
├── tools/
│   ├── build_assets.py    统一构建全部素材（抠像+对齐+共用画布）
│   ├── build_motion.py    算各帧质心 -> assets/motion.json（运行时帧间插值用）
│   ├── process_assets.py  素材流水线：视频/图片 -> 透明序列帧
│   └── smoke_test.py      启动后自动退出，验证框架
├── raw/                   原始绿幕素材（视频/图片，处理前）
├── assets/                各动作的透明序列帧（当前为空目录）
├── requirements.txt       运行依赖（仅 PySide6）
├── requirements-tools.txt 处理素材/打包依赖
└── build.bat              一键打包成单个 exe
```

## 处理素材

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-tools.txt

.\.venv\Scripts\python.exe tools\process_assets.py --input raw\walk.mp4 --action walk --method chroma --fps 12 --stabilize
.\.venv\Scripts\python.exe tools\process_assets.py --input raw\eat.mp4 --action eat --method chroma
```

输出到 `assets/<action>/frame_XXXX.png`，程序下次启动即生效。

## 打包

```powershell
dotnet build shell\NaiwaShell\NaiwaShell.csproj -c Release
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\build.bat
# 产物: dist\Naiwa.exe
```

`build.bat` 会先构建 64 位 Explorer COM 扩展，再把它打进主程序。目标电脑需要
安装 **.NET 8 Runtime x64**。首次运行时，主程序把扩展复制到
`%LOCALAPPDATA%\Naiwa\shell\` 并按当前用户注册，不需要管理员。若使用用户目录
里的便携 .NET，设置运行时路径后需重新登录 Windows（或重启 Explorer）再使用菜单。

开发时若只想启动桌宠、不改资源管理器注册表：

```powershell
$env:NAIWA_SKIP_SHELL_REG = "1"
.\.venv\Scripts\python.exe run.py
```

手动注册/反注册：

```powershell
powershell -ExecutionPolicy Bypass -File shell\NaiwaShell\register.ps1
powershell -ExecutionPolicy Bypass -File shell\NaiwaShell\unregister.ps1
```

Windows 11 若第一层菜单没显示，请在「显示更多选项」中使用。
若奶蛙已经运行，经典菜单仍没有入口：本机 Windows 11（26100）已复现 Shell
忽略用户级 COM 注册的问题。仅检查注册表或直接创建 COM 对象不能验证菜单正常。
在 **64 位管理员 PowerShell** 中执行一次兼容注册：

```powershell
powershell -ExecutionPolicy Bypass -File F:\naiwa\shell\NaiwaShell\register.ps1 -Machine
```

该选项将扩展复制到 `%ProgramFiles%\Naiwa\shell\<内容版本>\`，并登记机器级 COM
类；右键菜单关联仍只写入当前用户。日常运行奶蛙不需要管理员权限。不同构建使用
不同目录，避免覆盖 Explorer 正在使用的 DLL；相同构建重复注册会跳过相同文件。
这仍需要 .NET 8 x64 运行时。使用用户目录中的 .NET 时，Explorer 也必须能找到它。
只在奶蛙运行、且选中桌面文件系统项目时显示入口。

卸载兼容注册时，先退出奶蛙，再在管理员 PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File F:\naiwa\shell\NaiwaShell\unregister.ps1 -Machine
```

卸载只移除奶蛙的菜单/COM 注册，保留安装文件；重新启动奶蛙仍会按原逻辑尝试用户级注册。
摧毁使用独立的转身、坐压、起身、回身和闻手五段素材。回身段使用销毁1倒放、不镜像，
让侧身站姿自然接回正面和闻手动作。`销毁2`完整播放结束时
移入回收站，随后继续播放收尾动作。素材构建：`python tools/build_destroy_assets.py`；
完整流程验证：`python tools/verify_destroy_flow.py --real-recycle`（仅操作脚本新建的临时文件）。

## 交互说明

- **左键拖动**：把奶蛙拎起来移动，拖动时随手速左右晃动，松手回正。
- **右键**：弹出菜单（玩耍 / 洗澡 / 吃饭 / 睡觉 / 退出）。
- **桌面文件右键**：奶蛙运行时出现「召唤奶蛙摧毁」；点中同一个图标确认，
  坐压段（销毁2）结束后移入回收站，再播放起身和收尾动作。Esc 或右键覆盖层可取消。
- 不操作时：自动在桌面上发呆与散步，偶尔舔手 / 打哈欠；久无互动会自动睡觉。
