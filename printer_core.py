# -*- coding: utf-8 -*-
"""
打印机核心：枚举打印机、校验打印机、把渲染好的图片按选项发送到打印机。
依赖：pywin32 + pillow

说明：
    新版 pywin32 的 PyCDC 不再提供 GetDevMode/ResetDC，
    因此这里采用「临时修改打印机默认 DEVMODE -> 创建 DC 打印 -> 恢复」的方式应用选项；
    方向与黑白同时有图片层的兜底（旋转 / 灰度），保证任何驱动下输出都正确。
"""
import time

import win32print
import win32ui
import win32con
from PIL import Image, ImageWin, ImageDraw, ImageFont

# ---- DEVMODE 常量 ----
DM_ORIENTATION_PORTRAIT = 1
DM_ORIENTATION_LANDSCAPE = 2
DM_COLOR_COLOR = 1
DM_COLOR_MONOCHROME = 2
DM_DUPLEX_SIMPLEX = 1     # 单面
DM_DUPLEX_HORIZONTAL = 2  # 短边翻转（横装双面）
DM_DUPLEX_VERTICAL = 3    # 长边翻转（竖装双面）

# DEVMODE dmFields 对应的位
_DM_FIELD_BITS = {
    'Orientation': 0x0001,
    'PaperSize': 0x0002,
    'Color': 0x0008,
    'Duplex': 0x1000,
}

# Windows dmPaperSize 常用纸张映射
PAPER_SIZES = {
    'A3': 8, 'A4': 9, 'A5': 11, 'A6': 70,
    'B4': 12, 'B5': 13,
    'Letter': 1, 'Legal': 5, 'Executive': 7,
}

# 虚拟打印机特征（用于识别，避免默认选到它们）
_VIRTUAL_KEYWORDS = (
    'microsoft print to pdf', 'microsoft print', 'xps',
    'onenote', 'fax', 'adobe pdf', 'pdf creator',
)


class PrinterError(Exception):
    pass


def _enum_field(info, idx, key):
    """兼容 pywin32 返回的两种结构：字典（新）或元组（旧）"""
    try:
        return info.get(key, '')
    except Exception:
        try:
            return info[idx]
        except Exception:
            return ''


def list_printers():
    """返回本机可用打印机列表：[{name, port, driver, virtual}]"""
    out = []
    try:
        infos = win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
            None, 2,
        )
    except Exception:
        infos = []
    for info in infos:
        name = _enum_field(info, 1, 'pPrinterName')
        port = _enum_field(info, 3, 'pPortName')
        driver = _enum_field(info, 4, 'pDriverName')
        low = (name + ' ' + driver).lower()
        virtual = any(k in low for k in _VIRTUAL_KEYWORDS)
        out.append({'name': name, 'port': port, 'driver': driver, 'virtual': virtual})
    return out


def printer_exists(name):
    if not name:
        return False
    try:
        return any(p['name'] == name for p in list_printers())
    except Exception:
        return False


def pick_default(printers, configured='auto'):
    """选择默认打印机：先按配置，其次实体 USB 打印机，再其次任一实体打印机"""
    if configured and configured != 'auto':
        for p in printers:
            if p['name'] == configured:
                return p
    for p in printers:
        if not p['virtual'] and str(p['port']).upper().startswith('USB'):
            return p
    for p in printers:
        if not p['virtual']:
            return p
    return printers[0] if printers else None


def _printer_info2(name, access=None):
    """读取打印机 PRINTER_INFO_2（默认只读权限；写操作传 PRINTER_ALL_ACCESS）"""
    defaults = None
    if access:
        defaults = {'DesiredAccess': access}
    hp = win32print.OpenPrinter(name, defaults)
    try:
        return win32print.GetPrinter(hp, 2)
    finally:
        win32print.ClosePrinter(hp)


def _apply_devmode(name, changes):
    """
    临时把打印机默认 DEVMODE 改为 changes（{属性名: 值}），返回 restore 函数。
    需要管理员权限（PRINTER_ALL_ACCESS）；无权限时抛出异常，由调用方退回图片层补偿。
    """
    if not changes:
        return lambda: None

    info2 = _printer_info2(name, win32print.PRINTER_ALL_ACCESS)
    dm = info2['pDevMode']
    saved = {'Fields': dm.Fields}
    for k, v in changes.items():
        saved[k] = getattr(dm, k)
        setattr(dm, k, v)
        dm.Fields = dm.Fields | _DM_FIELD_BITS.get(k, 0)
    hp = win32print.OpenPrinter(name, {'DesiredAccess': win32print.PRINTER_ALL_ACCESS})
    try:
        win32print.SetPrinter(hp, 2, info2, 0)
    finally:
        win32print.ClosePrinter(hp)

    def restore():
        try:
            info2b = _printer_info2(name, win32print.PRINTER_ALL_ACCESS)
            dmb = info2b['pDevMode']
            for k, v in saved.items():
                setattr(dmb, k, v)
            hp2 = win32print.OpenPrinter(name, {'DesiredAccess': win32print.PRINTER_ALL_ACCESS})
            try:
                win32print.SetPrinter(hp2, 2, info2b, 0)
            finally:
                win32print.ClosePrinter(hp2)
        except Exception:
            pass

    return restore


def _draw_image(hdc, img, page_w, page_h, options):
    """把单张图片按选项绘制到打印机当前页面（居中等比缩放）"""
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return

    fit = options.get('fit', 'fit')
    if fit == 'stretch':
        dw, dh = page_w, page_h
    elif fit == 'original':
        # 按 96 DPI 的物理尺寸理解原图，但不超过纸张
        dpi_x = hdc.GetDeviceCaps(win32con.LOGPIXELSX) or 96
        dpi_y = hdc.GetDeviceCaps(win32con.LOGPIXELSY) or 96
        ow = int(iw * dpi_x / 96.0)
        oh = int(ih * dpi_y / 96.0)
        scale = min(1.0, page_w / ow, page_h / oh)
        dw = max(1, int(ow * scale))
        dh = max(1, int(oh * scale))
    else:  # fit：缩放适配页面
        scale = min(page_w / iw, page_h / ih)
        dw = max(1, int(iw * scale))
        dh = max(1, int(ih * scale))

    x = max(0, (page_w - dw) // 2)
    y = max(0, (page_h - dh) // 2)
    dib = ImageWin.Dib(img.convert('RGB'))
    dib.draw(hdc.GetHandleOutput(), (x, y, x + dw, y + dh))


def print_images(images, printer_name, options=None):
    """
    打印一组图片（每张一页）。
    options:
        copies: int 份数（默认 1）
        orientation: 'portrait' | 'landscape'
        color: 'color' | 'bw'
        duplex: 'simplex' | 'long'(长边) | 'short'(短边)
        paper: 'A4' | 'A5' | 'B5' | 'Letter' | 'Legal' | 'A3' | ...
        fit: 'fit' | 'original' | 'stretch'
        docname: str 任务名
    返回 (页数, 份数)
    """
    options = options or {}
    copies = max(1, int(options.get('copies', 1) or 1))
    orientation = options.get('orientation', 'portrait')
    color = options.get('color', 'color')
    duplex = options.get('duplex', 'simplex')
    paper = options.get('paper', 'A4')
    docname = options.get('docname', 'Web 打印任务') or 'Web 打印任务'

    if not printer_exists(printer_name):
        raise PrinterError('打印机不存在或未连接：%s' % printer_name)

    # 需要应用到打印机默认设置的项（需管理员权限；失败则退回默认，方向/黑白仍有图片层兜底）
    changes = {}
    changes['Orientation'] = DM_ORIENTATION_LANDSCAPE if orientation == 'landscape' else DM_ORIENTATION_PORTRAIT
    changes['Color'] = DM_COLOR_MONOCHROME if color == 'bw' else DM_COLOR_COLOR
    if duplex == 'long':
        changes['Duplex'] = DM_DUPLEX_VERTICAL
    elif duplex == 'short':
        changes['Duplex'] = DM_DUPLEX_HORIZONTAL
    else:
        changes['Duplex'] = DM_DUPLEX_SIMPLEX
    if paper in PAPER_SIZES:
        changes['PaperSize'] = PAPER_SIZES[paper]

    restore = None
    try:
        restore = _apply_devmode(printer_name, changes)
    except Exception:
        restore = None  # 无权限：继续用打印机默认，靠图片层兜底

    hdc = win32ui.CreateDC()
    try:
        hdc.CreatePrinterDC(printer_name)
        # DC 已捕获设置，立即恢复打印机默认值，把影响窗口缩到最短
        if restore is not None:
            try:
                restore()
            except Exception:
                pass
            restore = None

        hdc.StartDoc(docname)
        try:
            page_w = hdc.GetDeviceCaps(win32con.HORZRES)
            page_h = hdc.GetDeviceCaps(win32con.VERTRES)
            landscape_page = page_w > page_h
            want_landscape = orientation == 'landscape'
            for _ in range(copies):
                for img in images:
                    if color == 'bw':
                        img = img.convert('L').convert('RGB')
                    if want_landscape != landscape_page:
                        img = img.rotate(90, expand=True)
                    hdc.StartPage()
                    _draw_image(hdc, img, page_w, page_h, options)
                    hdc.EndPage()
        finally:
            hdc.EndDoc()
    except Exception as e:
        raise PrinterError('打印失败：%s' % e)
    finally:
        try:
            hdc.DeleteDC()
        except Exception:
            pass
        if restore is not None:
            restore()
    return len(images), copies


def open_dc_check(printer_name):
    """只验证能否打开打印机 DC（不产生任何打印输出），用于连接自检"""
    if not printer_exists(printer_name):
        raise PrinterError('打印机不存在或未连接：%s' % printer_name)
    hdc = win32ui.CreateDC()
    try:
        hdc.CreatePrinterDC(printer_name)
        dm = _printer_info2(printer_name)['pDevMode']
        return {
            'name': printer_name,
            'paper': dm.PaperSize,
            'orientation': dm.Orientation,
            'page': '%dx%d' % (hdc.GetDeviceCaps(win32con.HORZRES), hdc.GetDeviceCaps(win32con.VERTRES)),
        }
    except Exception as e:
        raise PrinterError('无法打开打印机 %s：%s' % (printer_name, e))
    finally:
        try:
            hdc.DeleteDC()
        except Exception:
            pass


def make_test_page(printer_name, copies=1, quality_dpi=150):
    """生成一张打印服务测试页（A4 @150dpi）"""
    dpi = 150
    w = int(8.27 * dpi)
    h = int(11.69 * dpi)
    img = Image.new('RGB', (w, h), 'white')
    d = ImageDraw.Draw(img)
    try:
        font_t = ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc', int(dpi * 0.32))
        font_b = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', int(dpi * 0.20))
    except Exception:
        font_t = ImageFont.load_default()
        font_b = ImageFont.load_default()

    # 顶部色条
    d.rectangle([0, 0, w, int(dpi * 0.5)], fill=(37, 99, 235))
    # 标题
    d.text((int(dpi * 0.6), int(dpi * 0.8)), '打印服务测试页', fill=(20, 30, 60), font=font_t)
    # 信息
    lines = [
        '打印机：%s' % printer_name,
        '打印时间：%s' % time.strftime('%Y-%m-%d %H:%M:%S'),
        '份数：%d  纸张：A4' % copies,
        '',
        '如果本页内容清晰、无偏移，说明打印服务一切正常。',
        '如需调整打印选项（双面、黑白、纸张等），请回到打印页面重新设置。',
    ]
    y = int(dpi * 2.2)
    for ln in lines:
        d.text((int(dpi * 0.6), y), ln, fill=(40, 50, 70), font=font_b)
        y += int(dpi * 0.55)
    # 底部圆点装饰
    for i in range(6):
        cx = int(dpi * (1.2 + i * 1.2))
        d.ellipse([cx - 12, h - int(dpi * 0.9) - 12, cx + 12, h - int(dpi * 0.9) + 12],
                  fill=(37, 99, 235))
    return img
