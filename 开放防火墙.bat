@echo off
title Open Firewall Port 8000
net session >nul 2>&1
if errorlevel 1 (
    echo Please right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)
netsh advfirewall firewall delete rule name="WebPrintServer" >nul 2>&1
netsh advfirewall firewall add rule name="WebPrintServer" dir=in action=allow protocol=TCP localport=8000 >nul
echo Firewall port 8000 opened for LAN access.
pause >nul
