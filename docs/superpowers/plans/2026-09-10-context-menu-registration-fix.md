# 奶蛙右键入口兼容修复计划

**Goal:** 修复本机 Windows 11 26100 忽略 HKCU COM 注册导致经典菜单缺少奶蛙入口的问题。

**证据:** 奶蛙运行时，直接 Initialize / QueryContextMenu 返回 1；Shell 构造的真实菜单无入口。仅临时增加 HKLM 的同一 CLSID 后真实菜单出现入口，移除后恢复缺失。

**Architecture:** 保留现有 COM 与管道、确认和回收流程。注册脚本增加显式 -Machine 选项，把扩展复制到 Program Files 的内容版本目录，登记机器级 CLSID。菜单关联保持当前用户范围。默认自动 HKCU 注册不提升权限。

**Tech Stack:** Python / PySide6、C# .NET 8、PowerShell、Windows Shell COM。

- [x] 更新 register.ps1，支持管理员运行 -Machine，预检构建文件并避免覆盖 Explorer 正占用的 DLL。
- [x] 更新 unregister.ps1 与 README，提供对应卸载方式，说明自动用户级注册的兼容限制。
- [x] 在本机应用注册，使用真实 Shell 菜单验证文件、文件夹、快捷方式，验证非桌面不出现。不调用真实文件销毁。

不提交、不推送。不重启 Explorer 或系统。

## 验证结果

- 本机应用 register.ps1 -Machine 后，真实 Shell 菜单出现奶蛙入口；用户已确认经典菜单可见。
- 桌面 Word 文件、临时文件夹、真实 .lnk 快捷方式均只出现一个入口；非桌面 README 无入口。
- 同一构建重复注册成功；两份 PowerShell 脚本通过语法解析。
- 既有 Python 测试此前使用隔离管道验证：28 passed，1 个实际回收测试未运行；本次未修改 Python 功能代码。
- 临时桌面测试目录已清理；未操作用户文件的销毁，未验证完整动画到回收流程。
- 未重启 Explorer，未提交或推送。当前修复安装目录：C:\Program Files\Naiwa\shell\3f1f6da19e3c16bc9761。
