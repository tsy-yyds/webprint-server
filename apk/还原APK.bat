@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "共享打印.apk.b64" (echo 没找到 共享打印.apk.b64，请与本文件放同一文件夹 & pause & exit /b)
certutil -decode "共享打印.apk.b64" "共享打印.apk" >nul 2>&1
if exist "共享打印.apk" (echo 还原成功：共享打印.apk（复制到手机安装即可）) else (echo 还原失败，请确认 b64 文件完整)
pause
