@echo off
title Install WebPrint Server
cd /d "%~dp0"
echo ============================================
echo   WebPrint - Installing dependencies
echo   (first time only, about 1-2 minutes)
echo ============================================
py -3 -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo.
    echo [Retry with python command]...
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo.
echo Done. You can close this window.
pause >nul
