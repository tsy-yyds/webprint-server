@echo off
title Start WebPrint Server
cd /d "%~dp0"
set PORT=8000

echo Checking dependencies...
py -3 -c "import flask, win32print, fitz, PIL" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Dependencies are missing. Please run install.bat first.
    pause
    exit /b 1
)

echo Starting server in background...
start "" wscript.exe "%~dp0run_hidden.vbs"

echo Waiting for server...
timeout /t 3 >nul
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/api/info' -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
if errorlevel 1 (
    echo.
    echo Server did not respond. Please check logs\server.log for errors.
    pause
    exit /b 1
)

echo Opening browser...
start "" "http://127.0.0.1:%PORT%"
exit /b 0
