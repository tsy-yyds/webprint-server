# 共享打印服务（Web Print Server）

把电脑上的 **USB 打印机**变成 **手机和电脑都能用的网络打印机**。打印机不需要支持网络打印，电脑也只需要局域网/内网。

```
手机 / 电脑浏览器
   │  局域网：http://电脑IP:8000
   │  外网：  https://xxxx.cpolar.top（免费穿透）
   ▼
打印电脑上的「共享打印服务」（本工程，后台静默运行）
   ▼
USB 打印机（如 Samsung SCX-4x21）
```

## 功能

- 🖨 **打印到纸**：上传 PDF / 图片 / TXT / Word / Excel / PPT，选择打印机与打印方式后提交打印，后台串行队列逐个打印
- 🔄 **手动双面**：先打印奇数页，手机弹出图文教程提示翻面放纸，点「下一步」后自动打印背面（偶数页倒序，页码不乱），支持取消重打
- 📄 **打印到 PDF**：把文件转成 PDF 保存到电脑「打印输出」文件夹，手机/电脑在网页上直接点「下载」
- 📱 **手机套壳**：网页是 PWA，浏览器「添加到主屏幕」后就是独立 App
- 🔌 **不依赖网络打印机**：直接用 win32 API 驱动本机 USB 打印机
- 🌐 **外网打印**：支持 cpolar / Tailscale 免费穿透（见《使用说明.md》)
- 🔒 **访问密码**：config.json 里可设置 PIN，防止别人乱打

## 快速开始（Windows）

1. 安装依赖：双击 `install.bat`（自动用清华镜像装 Flask / PyMuPDF / pywin32 / Pillow）
2. 启动：双击 `start.bat`（后台静默运行，无黑窗口，自动打开网页）
3. 手机连同一 WiFi，浏览器打开 `http://电脑IP:8000` 即可打印
4. 停止：双击 `stop.bat`；开机自启见 `启用开机自启.bat`

> 要求：Windows 10/11 + Python 3.9+。Word/Excel/PPT 转换需要本机装有 Office 或 WPS。
> 详细说明（含外网穿透、常见问题、安全提醒）见 **《使用说明.md》**。

## 目录结构

```
web/               手机端网页界面（单文件 index.html，零 CDN 依赖 + PWA）
app.py             Flask 主服务（API / 页面 / 托盘 / PIN / 配置）
printer_core.py    打印机核心（枚举 / DEVMODE 双通道 / 打印）
file_render.py     文件渲染（PDF/图片/TXT/Office 转图片或 PDF）
job_queue.py       打印任务队列（串行 / 手动双面等待 / 取消）
config.json        配置（端口 / PIN / 上传上限 / 分辨率）
install.bat        一键安装依赖
start.bat          后台静默启动
start_admin.bat    管理员模式启动（纸张/双面选项完整生效）
stop.bat           停止服务
使用说明.md         完整使用文档（手机用法 / 外网方案 / FAQ）
```

## 技术栈

Python 3 + Flask + pywin32（win32print/win32ui）+ Pillow + PyMuPDF；前端原生 HTML/CSS/JS（PWA）。

## 说明

- 手动双面的翻面方向按「打印机打印面朝下出纸」设计（先奇数页，翻面后偶数页倒序）；放纸方向以你平时手动双面的习惯为准，教程弹窗里有图文提示。
- 本工程精简版只保留源码与脚本；运行日志（logs/）、任务暂存（jobs/）、PDF 输出（打印输出/）均为运行时产物，已加入 .gitignore。
