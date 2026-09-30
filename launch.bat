@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [hearth] first run - setting things up
    call install.bat || exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" -m hearth
endlocal
