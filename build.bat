@echo off
REM Build dist\Naiwa.exe. Requires PyInstaller and .NET 8 SDK.

setlocal
cd /d %~dp0

set PY=.venv\Scripts\python.exe
if not exist %PY% set PY=python

set DOTNET=dotnet
if exist "%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe" set DOTNET="%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe"

%DOTNET% build shell\NaiwaShell\NaiwaShell.csproj -c Release
if errorlevel 1 (
  echo NaiwaShell 构建失败，请先安装 .NET 8 SDK。
  exit /b 1
)

%PY% -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name Naiwa ^
  --add-data "assets;assets" ^
  --add-data "shell\NaiwaShell\bin\Release\net8.0-windows;NaiwaShell" ^
  run.py
if errorlevel 1 (
  echo PyInstaller build failed.
  exit /b 1
)

echo.
echo Build complete -^> dist\Naiwa.exe
endlocal
