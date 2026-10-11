@echo off
chcp 65001 >nul
title 打包共享打印桌面助手
echo ============================================
echo  共享打印 · 桌面助手 v2.0 打包脚本
echo ============================================
echo.
echo 将 app.py + ui.html 打包成单文件 exe（网页级界面，独立运行）
echo 要求：已安装 Python 3.9+、pywebview、PyInstaller
echo   （pip install pywebview pyinstaller）
echo.
echo 按任意键开始打包...
pause >nul

py -3 -m PyInstaller --onefile --windowed --name "共享打印桌面助手" --add-data "ui.html;." --collect-all webview app.py

echo.
echo 打包完成！exe 在 dist\ 目录：dist\共享打印桌面助手.exe
echo.
pause