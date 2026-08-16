@echo off
REM ============================================================
REM  Dashboard backend launcher (hidden, no console window)
REM  Starts api/server.py on http://127.0.0.1:8765/
REM  Uses pythonw.exe so no black console box stays on desktop.
REM  Logs go to api/server.log.
REM ============================================================

setlocal
set PY="C:\Users\IceFly\AppData\Local\Programs\Python\Python312\pythonw.exe"
set APPDIR=D:\IceFly\Dashboard\api

REM --- kill any stale process holding port 8765 ---
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
)

cd /d "%APPDIR%"

REM --- launch hidden (pythonw has no console; /b avoids a new window) ---
start "" /b %PY% server.py

REM --- wait then self-check, then auto-exit (no pause, no hanging window) ---
timeout /t 3 /nobreak >nul
netstat -ano | findstr ":8765" | findstr "LISTENING" >nul && (
    echo [OK] Dashboard server is running on http://127.0.0.1:8765/
    echo      Logs: %APPDIR%\server.log
) || (
    echo [FAIL] Server did not start. Check %APPDIR%\server.log
)
timeout /t 2 /nobreak >nul
endlocal
