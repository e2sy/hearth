@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [hearth] first run - setting things up
    call install.bat || exit /b 1
)

echo [hearth] starting in debug console mode...
".venv\Scripts\python.exe" -u -m hearth %*
set "EXIT_CODE=%errorlevel%"

if %EXIT_CODE% neq 0 (
    echo.
    echo [hearth] process terminated with exit code %EXIT_CODE%
    pause
)
endlocal & exit /b %EXIT_CODE%
