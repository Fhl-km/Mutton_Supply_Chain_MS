@echo off
cd /d "%~dp0"
rem Keep this file ASCII-only: cmd.exe cannot parse UTF-8 batch files with CJK text.
set "PYTHONPATH=%~dp0src"

if not exist ".venv\Scripts\python.exe" goto no_venv

".venv\Scripts\python.exe" -c "import PySide6, openpyxl" >nul 2>&1
if errorlevel 1 goto install_deps

start "" ".venv\Scripts\pythonw.exe" -m mscm
exit /b 0

:install_deps
echo [INFO] Dependencies missing, installing PySide6 / openpyxl ...
".venv\Scripts\python.exe" -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -e .
if errorlevel 1 goto pip_failed
start "" ".venv\Scripts\pythonw.exe" -m mscm
exit /b 0

:pip_failed
echo [ERROR] pip install failed. Check your network and run this file again.
pause
exit /b 1

:no_venv
echo [ERROR] .venv not found in "%~dp0"
echo Run these commands in this folder first:
echo     python -m venv .venv
echo     .venv\Scripts\python -m pip install -e .
pause
exit /b 1
