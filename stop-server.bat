@echo off
REM ============================================================
REM  Dashboard backend stopper
REM  Kills the python/pythonw process listening on port 8765.
REM ============================================================

setlocal enabledelayedexpansion
set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
    echo Stopping Dashboard server - PID %%P
    taskkill /F /PID %%P >nul 2>&1
    set "FOUND=1"
)
if defined FOUND (
    echo [OK] Dashboard server stopped.
) else (
    echo [--] No Dashboard server was running on port 8765.
)
timeout /t 2 /nobreak >nul
endlocal
