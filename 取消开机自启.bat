@echo off
title Disable Auto-Start
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "WebPrintServer" /f >nul 2>&1
echo Auto-start disabled.
pause >nul
