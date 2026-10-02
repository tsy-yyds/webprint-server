@echo off
title Enable Auto-Start
cd /d "%~dp0"
set KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run
set VAL=wscript.exe "%~dp0run_hidden.vbs"
reg add "%KEY%" /v "WebPrintServer" /t REG_SZ /d "%VAL%" /f >nul
echo Auto-start enabled: the print server will run silently after login.
pause >nul
