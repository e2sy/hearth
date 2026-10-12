@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo [hearth] creating the local environment
    %PY% -m venv .venv || exit /b 1
)

echo [hearth] installing dependencies
rem The pip self-upgrade is best-effort: on locked-down corporate boxes
rem with proxy / cert setups it can fail even when the requirements
rem install (which uses the bundled pip) would have worked. Log the
rem failure and continue rather than silently masking it.
call ".venv\Scripts\python.exe" -m pip install --upgrade pip || (
    echo [hearth] pip self-upgrade failed - continuing with the bundled pip
)
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (
    echo [hearth] dependency install failed - check the network and rerun install.bat
    exit /b 1
)

echo [hearth] ready - run launch.bat
endlocal
