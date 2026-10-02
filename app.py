# -*- coding: utf-8 -*-
"""
共享打印服务器主程序
===============================
把 USB 打印机变成 局域网 / 外网（穿透）可用的 Web 打印机。

启动：
    前台调试：  python app.py
    后台静默：  双击 start.bat  （或直接双击 run_hidden.vbs）
    停止：      双击 stop.bat

说明：
    - 网页界面在 web/index.html，零外部依赖，离线可用
    - 手机浏览器打开后可选"添加到主屏幕"（PWA 套壳），用起来像 App
    - 外网访问：见 使用说明.md（cpolar / Tailscale 免费穿透）
"""
import json
import logging
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from file_render import (  # noqa: E402
    RenderError, UnsupportedFormatError, export_to_pdf, merge_pdfs, render_file,
)
from job_queue import JobManager  # noqa: E402
from printer_core import (  # noqa: E402
    PrinterError, list_printers, make_test_page, open_dc_check,
    pick_default, print_images,
)

# ============================================================ 配置
_DEFAULT_CONFIG = {
    'host': '0.0.0.0',
    'port': 8000,
    'pin': '',
    'max_upload_mb': 100,
    'default_printer': 'auto',
    'job_keep_days': 7,
    'dpi_quality': {'draft': 150, 'standard': 200, 'high': 300},
}

CONFIG_PATH = BASE_DIR / 'config.json'


def load_config():
    cfg = dict(_DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            # utf-8-sig：兼容记事本/PowerShell 保存时可能带上的 BOM
            data = json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig'))
            if isinstance(data, dict):
                cfg.update(data)
        except Exception as e:
            print('[配置] config.json 解析失败，使用默认配置：', e)
    return cfg


CONFIG = load_config()
HOST = CONFIG.get('host', '0.0.0.0')
PORT = int(CONFIG.get('port', 8000))
PIN = str(CONFIG.get('pin') or '').strip()
MAX_UPLOAD = int(CONFIG.get('max_upload_mb', 100)) * 1024 * 1024

JOBS_DIR = BASE_DIR / 'jobs'
LOGS_DIR = BASE_DIR / 'logs'
PDF_DIR = BASE_DIR / '打印输出'
JOBS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)

# ============================================================ 日志
_logger = logging.getLogger('webprint')
_logger.setLevel(logging.INFO)
_fh = RotatingFileHandler(str(LOGS_DIR / 'server.log'), maxBytes=2 * 1024 * 1024,
                          backupCount=3, encoding='utf-8')
_fh.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s'))
_logger.addHandler(_fh)
# pythonw 静默运行时没有 stdout/stderr，跳过控制台输出
if sys.stdout is not None:
    _console = logging.StreamHandler(sys.stdout)
    _console.setFormatter(logging.Formatter('[%(asctime)s] %(message)s'))
    _logger.addHandler(_console)

# ============================================================ 应用与任务队列
app = Flask(__name__, static_folder='web', static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD

START_TIME = time.time()


# 模拟打印开关：设置环境变量 WEBPRINT_MOCK=1 时不真正输出纸张，
# 只记录日志（用于调试 / 自测，不影响正常使用）
MOCK_PRINT = os.environ.get('WEBPRINT_MOCK') == '1'


def _print_fn(images, printer, options):
    if MOCK_PRINT:
        _log('[模拟打印] %d 页 -> %s，选项：%s' % (
            len(images), printer,
            {k: options.get(k) for k in ('copies', 'orientation', 'color', 'duplex', 'paper', 'fit')},
        ))
        return len(images), max(1, int(options.get('copies', 1) or 1))
    return print_images(images, printer, options)


def _log(msg):
    _logger.info(msg)


jobs = JobManager(
    jobs_dir=str(JOBS_DIR),
    print_fn=_print_fn,
    render_fn=render_file,
    export_fn=export_to_pdf,
    exports_dir=str(PDF_DIR),
    quality_map=CONFIG.get('dpi_quality', {'draft': 150, 'standard': 200, 'high': 300}),
    keep_days=int(CONFIG.get('job_keep_days', 7)),
    log=_log,
)


def get_local_ips():
    ips = set()
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith('127.'):
                ips.add(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(('223.5.5.5', 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(ips)


def check_auth():
    if not PIN:
        return True
    return request.headers.get('X-Print-Pin', '') == PIN


def _printer_list_payload():
    printers = list_printers()
    default = pick_default(printers, CONFIG.get('default_printer', 'auto'))
    payload = []
    for p in printers:
        p = dict(p)
        p['is_default'] = bool(default and p['name'] == default['name'])
        payload.append(p)
    return payload


# ============================================================ 页面
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


# ============================================================ API
@app.get('/api/info')
def api_info():
    printers = list_printers()
    default = pick_default(printers, CONFIG.get('default_printer', 'auto'))
    return jsonify({
        'ok': True,
        'name': '共享打印服务',
        'version': '1.1',
        'uptime': int(time.time() - START_TIME),
        'pin_required': bool(PIN),
        'pdf_export': True,
        'ips': get_local_ips(),
        'port': PORT,
        'printer_count': len(printers),
        'default_printer': default['name'] if default else None,
        'supported': SUPPORTED_HINTS.split(),
    })


@app.get('/api/printers')
def api_printers():
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    return jsonify({'ok': True, 'printers': _printer_list_payload()})


@app.post('/api/print')
def api_print():
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    files = request.files.getlist('files')
    if not files:
        return jsonify({'ok': False, 'error': '没有收到文件'}), 400
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({'ok': False, 'error': '没有收到文件'}), 400

    to_pdf = request.form.get('to_pdf') in ('1', 'true', 'yes', 'on')
    printer = (request.form.get('printer') or '').strip()
    if not to_pdf:
        if not printer:
            printers = list_printers()
            default = pick_default(printers, CONFIG.get('default_printer', 'auto'))
            printer = default['name'] if default else ''
        if not printer:
            return jsonify({'ok': False, 'error': '本机没有检测到可用打印机'}), 400
        if not any(p['name'] == printer for p in list_printers()):
            return jsonify({'ok': False, 'error': '打印机不存在或未连接：%s' % printer}), 400

    options = {
        'printer': printer,
        'to_pdf': to_pdf,
        'copies': max(1, min(99, int(request.form.get('copies', 1) or 1))),
        'orientation': request.form.get('orientation', 'portrait') in ('landscape', '横') and 'landscape' or 'portrait',
        'color': request.form.get('color', 'color') == 'bw' and 'bw' or 'color',
        'duplex': request.form.get('duplex', 'simplex'),
        'paper': request.form.get('paper', 'A4') or 'A4',
        'fit': request.form.get('fit', 'fit') or 'fit',
        'quality': request.form.get('quality', 'standard') or 'standard',
        'docname': (request.form.get('docname') or 'Web 打印').strip()[:60],
    }
    # 校验枚举值，防止非法值破坏打印
    if options['duplex'] not in ('simplex', 'long', 'short', 'manual'):
        options['duplex'] = 'simplex'
    if options['paper'] not in ('A3', 'A4', 'A5', 'A6', 'B4', 'B5', 'Letter', 'Legal', 'Executive'):
        options['paper'] = 'A4'
    if options['fit'] not in ('fit', 'original', 'stretch'):
        options['fit'] = 'fit'
    if options['quality'] not in ('draft', 'standard', 'high'):
        options['quality'] = 'standard'
    # 打印到 PDF / 手动双面：互斥且限制份数
    if to_pdf:
        options['duplex'] = 'simplex'
        options['copies'] = 1
    if options['duplex'] == 'manual':
        options['copies'] = 1

    try:
        job = jobs.create(files, options)
    except Exception as e:
        return jsonify({'ok': False, 'error': '创建任务失败：%s' % e}), 500
    _log('新任务 %s：%s -> %s' % (job['id'], ','.join(job['files']), printer))
    return jsonify({'ok': True, 'job_id': job['id']})


@app.post('/api/test-print')
def api_test_print():
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    printer = (request.form.get('printer') or '').strip()
    if not any(p['name'] == printer for p in list_printers()):
        return jsonify({'ok': False, 'error': '打印机不存在或未连接：%s' % printer}), 400
    try:
        copies = max(1, min(5, int(request.form.get('copies', 1) or 1)))
        img = make_test_page(printer, copies=copies)
        with jobs.print_lock:
            if MOCK_PRINT:
                _log('[模拟打印] 测试页 1 页 -> %s' % printer)
            else:
                print_images([img], printer, {
                    'copies': copies,
                    'orientation': 'portrait',
                    'color': 'color',
                    'duplex': 'simplex',
                    'paper': 'A4',
                    'fit': 'fit',
                    'docname': '打印服务测试页',
                })
        _log('测试页打印成功 -> %s' % printer)
        return jsonify({'ok': True})
    except Exception as e:
        _log('测试页打印失败：%s' % e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.post('/api/check-printer')
def api_check_printer():
    """自检打印机连接（不产生打印输出）"""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    printer = (request.form.get('printer') or '').strip()
    try:
        info = open_dc_check(printer)
        return jsonify({'ok': True, 'info': info})
    except PrinterError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.get('/api/jobs')
def api_jobs():
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    limit = min(100, int(request.args.get('limit', 50)))
    return jsonify({'ok': True, 'jobs': jobs.list(limit=limit)})


@app.get('/api/jobs/<jid>')
def api_job(jid):
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    job = jobs.get(jid)
    if not job:
        return jsonify({'ok': False, 'error': '任务不存在'}), 404
    return jsonify({'ok': True, 'job': job})


@app.post('/api/jobs/<jid>/continue')
def api_job_continue(jid):
    """手动双面：确认已翻面放回，继续打印背面"""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    ok, err = jobs.continue_job(jid)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True})


@app.post('/api/jobs/<jid>/cancel')
def api_job_cancel(jid):
    """取消等待翻面 / 排队中的任务"""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    ok, err = jobs.cancel_job(jid)
    if not ok:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True})


@app.get('/api/pdf-outputs')
def api_pdf_outputs():
    """列出“打印输出”文件夹中已生成的 PDF 文件"""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    items = []
    try:
        files = [p for p in PDF_DIR.glob('*.pdf') if not p.name.startswith('_tmp_')]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[:50]:
            st = p.stat()
            items.append({
                'name': p.name,
                'size': st.st_size,
                'created': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime)),
            })
    except Exception as e:
        return jsonify({'ok': False, 'error': '读取输出目录失败：%s' % e}), 500
    return jsonify({'ok': True, 'files': items})


@app.get('/download/<path:fname>')
def api_download(fname):
    """下载打印输出目录中的 PDF（send_from_directory 自带路径防护）"""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'PIN 不正确'}), 403
    from flask import send_file
    target = (PDF_DIR / fname).resolve()
    if not str(target).startswith(str(PDF_DIR.resolve())) or not target.is_file():
        return jsonify({'ok': False, 'error': '文件不存在'}), 404
    return send_file(str(target), as_attachment=True, download_name=target.name, mimetype='application/pdf')


# 上传超限提示
@app.errorhandler(413)
def too_large(_e):
    return jsonify({'ok': False, 'error': '文件过大，超过服务器限制（%d MB）' % (MAX_UPLOAD // 1048576)}), 413


@app.errorhandler(404)
def not_found(_e):
    return jsonify({'ok': False, 'error': '接口不存在'}), 404


# ============================================================ 托盘（可选）
_tray_thread = None


def _start_tray():
    global _tray_thread
    try:
        import pystray
        from PIL import Image as PILImage, ImageDraw
    except Exception:
        _log('未安装 pystray，跳过托盘图标（不影响功能）')
        return

    def make_icon():
        img = PILImage.new('RGB', (64, 64), (37, 99, 235))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([14, 20, 50, 52], 4, fill='white')
        d.rectangle([20, 12, 44, 22], fill='white')
        d.rectangle([26, 34, 38, 44], fill=(37, 99, 235))
        return img

    def on_open(_icon, _item):
        try:
            webbrowser.open('http://127.0.0.1:%d' % PORT)
        except Exception:
            pass

    def on_quit(_icon, _item):
        _icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem('打开打印页面', on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('退出服务', on_quit),
    )
    icon = pystray.Icon('webprint', make_icon(), '共享打印服务', menu)

    def run():
        try:
            icon.run()
        except Exception as e:
            _log('托盘图标运行异常（不影响功能）：%s' % e)

    _tray_thread = threading.Thread(target=run, daemon=True)
    _tray_thread.start()
    _log('托盘图标已启动')


# ============================================================ 主入口
def main():
    (BASE_DIR / 'pid.txt').write_text(str(os.getpid()), encoding='utf-8')

    _log('=' * 56)
    _log('共享打印服务启动')
    _log('网页地址（本机）：   http://127.0.0.1:%d' % PORT)
    for ip in get_local_ips():
        _log('局域网地址（手机）： http://%s:%d' % (ip, PORT))
    _log('默认打印机：%s' % (pick_default(list_printers(), CONFIG.get('default_printer', 'auto')) or {}).get('name', '无'))
    _log('外网访问方法见 使用说明.md（cpolar / Tailscale）')
    _log('=' * 56)

    if '--no-tray' not in sys.argv:
        _start_tray()

    try:
        app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)
    except OSError as e:
        _log('启动失败：%s（可能端口 %d 被占用，或防火墙拦截）' % (e, PORT))
        if '--no-tray' not in sys.argv:
            import time as _t
            _t.sleep(1)
        raise SystemExit(1)


SUPPORTED_HINTS = (
    '.pdf .png .jpg .jpeg .bmp .tif .tiff .webp .gif .txt '
    '.docx .doc .xlsx .xls .pptx .ppt'
)

if __name__ == '__main__':
    main()
