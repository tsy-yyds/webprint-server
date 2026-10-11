@echo off
chcp 65001 >nul
title 打包共享打印电脑客户端
echo ============================================
echo  共享打印 · 电脑客户端 打包脚本
echo ============================================
echo.
echo 本脚本将 client.py 打包成单文件 exe（无需 Python 环境即可运行）
echo 要求：已安装 Python 3.9+ 和 PyInstaller
echo   （pip install pyinstaller）
echo.
echo 按任意键开始打包...
pause >nul

py -3 -m PyInstaller --onefile --windowed --name "共享打印桌面版" --icon "..\build_icon.ico" client.py

echo.
echo 打包完成！exe 在 dist\ 目录：dist\共享打印桌面版.exe
echo.
pause
