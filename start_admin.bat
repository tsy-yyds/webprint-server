@echo off
title Start WebPrint Server (Admin Mode)
cd /d "%~dp0"
set PORT=8000

echo Checking dependencies...
py -3 -c "import flask, win32print, fitz, PIL" >nul 2>&1
if errorlevel 1 (
    echo Dependencies missing. Run install.bat first.
    pause
    exit /b 1
)

echo Starting server as administrator (a UAC prompt will appear, click Yes)...
powershell -NoProfile -Command "Start-Process -FilePath 'wscript.exe' -ArgumentList '\"%~dp0run_hidden.vbs\"' -Verb RunAs"
timeout /t 3 >nul
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/api/info' -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
if errorlevel 1 (
    echo Server did not respond. Check logs\server.log
    pause
    exit /b 1
)

echo Opening browser...
start "" "http://127.0.0.1:%PORT%"
exit /b 0
