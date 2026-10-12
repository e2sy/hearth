@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [hearth] first run - setting things up
    call install.bat || exit /b 1
)

rem Capture the per-user log directory so a silent pythonw.exe crash
rem still leaves a trace. ``pythonw`` is the GUI-subsystem launcher: by
rem design it has no console and no stderr, so a failed import (missing
rem dependency, broken venv, AV interference, PyQt6 DLL hell) would
rem otherwise look like "the app did nothing". We redirect stderr to a
rem startup-error log next to the rolling hearth.log; the app cleans
rem it up on a successful boot.
if not exist "%APPDATA%\hearth\Hearth" mkdir "%APPDATA%\hearth\Hearth"
set "ERR_LOG=%APPDATA%\hearth\Hearth\startup.err"

rem Try the silent GUI launch first. Stderr lands in the err log so a
rem crash leaves a breadcrumb instead of a vanishing window.
start "" ".venv\Scripts\pythonw.exe" -X dev -m hearth 2>"%ERR_LOG%"

rem Give the launcher a beat to actually fail (or not). ``start``
rem returns immediately, so we poll for the process; if it has
rem already died AND the err log is non-empty, we know the boot
rem failed and we can offer the debug console instead.
powershell -NoProfile -Command "Start-Sleep -Milliseconds 2500" >nul 2>nul

rem If the err log has content, the GUI boot crashed — surface it.
if exist "%ERR_LOG%" (
    for %%I in ("%ERR_LOG%") do if %%~zI gtr 0 (
        echo [hearth] the GUI launcher failed to start.
        echo [hearth] saved error log: %ERR_LOG%
        echo [hearth] rerun launch_debug.bat for an in-console traceback.
        echo.
        type "%ERR_LOG%"
        echo.
        pause
    ) else (
        rem Empty log on a successful boot — clean it up so a later
        rem crash doesn't surface stale output from the last good run.
        del "%ERR_LOG%" >nul 2>nul
    )
)

endlocal
