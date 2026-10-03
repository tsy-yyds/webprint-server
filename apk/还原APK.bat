@echo off
chcp 65001 >nul
cd /d "%~dp0"
copy /b b64_part1.txt+b64_part2.txt+b64_part3.txt+b64_part4.txt+b64_part5.txt+b64_part6.txt+b64_part7.txt+b64_part8a.txt+b64_part8b1.txt+b64_part8b2.txt+b64_part9.txt+b64_part10a.txt+b64_part10b.txt 共享打印.apk.b64 >nul
if not exist "共享打印.apk.b64" (echo 合并失败：请确认 13 个 b64_part*.txt 都在本文件夹 & pause & exit /b)
certutil -decode "共享打印.apk.b64" "共享打印.apk" >nul 2>&1
if exist "共享打印.apk" (echo 还原成功：共享打印.apk（复制到手机安装即可）) else (echo 还原失败，请确认 13 个分块文件完整、未损坏)
del "共享打印.apk.b64" >nul 2>&1
pause
