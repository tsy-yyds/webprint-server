@echo off
title Stop WebPrint Server
cd /d "%~dp0"
setlocal EnableDelayedExpansion
if exist pid.txt (
    set /p PID=<pid.txt
    taskkill /PID !PID! /F >nul 2>&1
    if errorlevel 1 (
        echo Server was not running.
    ) else (
        echo Server stopped.
    )
    del pid.txt >nul 2>&1
) else (
    echo No pid.txt found, trying to match app.py processes...
    powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'app\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output ('Stopped PID ' + $_.ProcessId) }"
)
pause >nul
