@echo off
REM Compile a tiny .NET Framework 4.x launcher next to run.py.
REM Uses the copy of csc.exe that ships with Windows.

setlocal
cd /d %~dp0

set CSC=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%SystemRoot%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo 找不到 csc.exe，无法编译启动器。
  exit /b 1
)

"%CSC%" /nologo /target:winexe /optimize+ ^
  /out:"..\..\run.exe" ^
  /r:System.Windows.Forms.dll ^
  /r:System.Drawing.dll ^
  StartNaiwa.cs
if errorlevel 1 exit /b 1

echo.
echo Built -^> run.exe
endlocal
