# -*- coding: utf-8 -*-
"""
文件渲染：把上传的文件统一渲染成 PIL 图片列表，交给打印核心。
支持：PDF / PNG/JPG/BMP/TIFF/WebP/GIF / TXT / Office（DOCX/DOC/XLSX/XLS/PPTX/PPT，需本机装有 Office 或 WPS）
"""
import io
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence


class RenderError(Exception):
    pass


class UnsupportedFormatError(RenderError):
    def __init__(self, ext):
        super().__init__(
            '暂不支持的文件格式：%s。支持的格式：PDF、PNG/JPG/BMP/TIFF/WebP、TXT，'
            '以及 Office 文档（DOCX/DOC/XLSX/XLS/PPTX/PPT，需本机装有 Office 或 WPS）。'
            % (ext or '未知')
        )


# ============================================================ PDF
def render_pdf(path, dpi=200):
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            raise RenderError('缺少 PyMuPDF 库，无法处理 PDF，请先运行 install.bat 安装依赖')
    imgs = []
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise RenderError('无法打开 PDF 文件：%s' % e)
    try:
        if doc.page_count == 0:
            raise RenderError('PDF 文件没有页面')
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
            img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            imgs.append(img)
    finally:
        doc.close()
    return imgs


# ============================================================ 图片
def render_image(path, dpi=200):
    imgs = []
    try:
        im = Image.open(path)
        fmt = (im.format or '').upper()
        # TIFF 扫描件支持多页；其他格式取第一帧
        frames = list(ImageSequence.Iterator(im)) if fmt == 'TIFF' else [im]
        for fr in frames[:100]:
            fr = ImageOps.exif_transpose(fr)
            if fr.mode not in ('RGB', 'L'):
                fr = fr.convert('RGB')
            if fr.mode == 'L':
                fr = fr.convert('RGB')
            imgs.append(fr.copy())
        im.close()
    except RenderError:
        raise
    except Exception as e:
        raise RenderError('无法读取图片：%s' % e)
    if not imgs:
        raise RenderError('图片文件为空')
    return imgs


# ============================================================ TXT
_FONT_CANDIDATES = ('msyh.ttc', 'msyhl.ttc', 'simhei.ttf', 'simsun.ttc', 'arialuni.ttf')


def _load_font(size):
    for name in _FONT_CANDIDATES:
        p = os.path.join(r'C:\Windows\Fonts', name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_text(path, dpi=200):
    raw = Path(path).read_bytes()
    text = None
    for enc in ('utf-8-sig', 'utf-8', 'gb18030', 'utf-16'):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        raise RenderError('无法识别文本文件编码（支持 UTF-8 / GBK / UTF-16）')

    page_w = int(8.27 * dpi)
    page_h = int(11.69 * dpi)
    margin = int(0.6 * dpi)
    font = _load_font(max(16, int(dpi * 0.16)))
    line_h = int(font.size * 1.6)
    max_w = page_w - 2 * margin

    # 按字符宽度换行
    lines = []
    for para in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if not para.strip():
            lines.append('')
            continue
        cur = ''
        for ch in para:
            if cur and font.getlength(cur + ch) > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)

    per = max(1, (page_h - 2 * margin) // line_h)
    imgs = []
    for start in range(0, len(lines), per):
        img = Image.new('RGB', (page_w, page_h), 'white')
        d = ImageDraw.Draw(img)
        y = margin
        for line in lines[start:start + per]:
            d.text((margin, y), line, fill=(0, 0, 0), font=font)
            y += line_h
        imgs.append(img)
    return imgs


# ============================================================ Office（COM 转 PDF）
def _try_com(progids, action):
    """依次尝试启动 COM 应用并执行 action(app)，成功则退出"""
    import win32com.client
    errors = []
    for pid in progids:
        app = None
        try:
            app = win32com.client.Dispatch(pid)
            result = action(app)
            return result
        except Exception as e:
            errors.append('%s: %s' % (pid, e))
        finally:
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
    raise RenderError('无法启动 Office/WPS 组件（%s），请确认本机已安装 Office 或 WPS' % ' / '.join(errors))


def _word_to_pdf(src, pdf):
    def do(app):
        doc = app.Documents.Open(src, ReadOnly=True)
        try:
            doc.ExportAsFixedFormat(pdf, 17)  # wdExportFormatPDF
        finally:
            doc.Close(False)
    _try_com(('Word.Application', 'KWPS.Application', 'wps.Application'), do)


def _excel_to_pdf(src, pdf):
    def do(app):
        wb = app.Workbooks.Open(src, ReadOnly=True)
        try:
            wb.ExportAsFixedFormat(0, pdf)  # xlTypePDF
        finally:
            wb.Close(False)
    _try_com(('Excel.Application', 'KET.Application', 'et.Application'), do)


def _ppt_to_pdf(src, pdf):
    def do(app):
        pres = app.Presentations.Open(src, ReadOnly=True, WithWindow=False)
        try:
            pres.SaveAs(pdf, 32)  # ppSaveAsPDF
        finally:
            pres.Close()
    _try_com(('PowerPoint.Application', 'KWPP.Application', 'wpp.Application'), do)


def _office_to_pdf(src):
    ext = Path(src).suffix.lower()
    fd, pdf = tempfile.mkstemp(suffix='.pdf', prefix='webprint_')
    os.close(fd)
    try:
        if ext in ('.docx', '.doc'):
            _word_to_pdf(src, pdf)
        elif ext in ('.xlsx', '.xls'):
            _excel_to_pdf(src, pdf)
        elif ext in ('.pptx', '.ppt'):
            _ppt_to_pdf(src, pdf)
        else:
            raise UnsupportedFormatError(ext)
    except RenderError:
        raise
    except Exception as e:
        raise RenderError('Office 转换失败：%s' % e)
    return pdf


def render_office(path, dpi=200):
    pdf = _office_to_pdf(path)
    try:
        return render_pdf(pdf, dpi)
    finally:
        try:
            os.remove(pdf)
        except Exception:
            pass


# ============================================================ 分发
_IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp', '.gif')
_OFFICE_EXTS = ('.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt')

_HANDLERS = {}
for _e in ('.pdf',):
    _HANDLERS[_e] = render_pdf
for _e in _IMAGE_EXTS:
    _HANDLERS[_e] = render_image
_HANDLERS['.txt'] = render_text
for _e in _OFFICE_EXTS:
    _HANDLERS[_e] = render_office

SUPPORTED_EXTS = tuple(sorted(_HANDLERS.keys()))


def render_file(path, dpi=200):
    ext = Path(path).suffix.lower()
    handler = _HANDLERS.get(ext)
    if handler is None:
        raise UnsupportedFormatError(ext)
    imgs = handler(path, dpi=dpi)
    if not imgs:
        raise RenderError('文件没有可打印的内容')
    return imgs


# ============================================================ 导出 PDF（打印到 PDF 用）
def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    return fitz


def _export_images_to_pdf(src, out_pdf, dpi):
    """图片 -> PDF：每张图一页，A4 居中适应"""
    fitz = _fitz()
    imgs = render_image(src, dpi=dpi)
    doc = fitz.open()
    try:
        for img in imgs:
            page = doc.new_page(width=595, height=842)  # A4 pt
            r = page.rect
            pr = r.width / r.height
            ir = img.width / img.height
            if ir >= pr:
                w = r.width
                h = r.width / ir
            else:
                h = r.height
                w = r.height * ir
            buf = io.BytesIO()
            img.convert('RGB').save(buf, format='PNG')
            page.insert_image(fitz.Rect((r.width - w) / 2, (r.height - h) / 2,
                                        (r.width + w) / 2, (r.height + h) / 2),
                              stream=buf.getvalue())
        doc.save(out_pdf, deflate=True)
    finally:
        doc.close()


def _export_text_to_pdf(src, out_pdf):
    """TXT -> PDF：A4 文本页，内置中文字体（可选中复制）"""
    raw = Path(src).read_bytes()
    text = None
    for enc in ('utf-8-sig', 'utf-8', 'gb18030', 'utf-16'):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        raise RenderError('无法识别文本文件编码（支持 UTF-8 / GBK / UTF-16）')

    fitz = _fitz()
    page_w, page_h = 595, 842
    margin = 48
    fontsize = 11
    line_h = 16

    def _split(para, width):
        lines = []
        cur = ''
        for ch in para:
            if cur and fitz.get_text_length(cur + ch, fontname='china-s', fontsize=fontsize) > width:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
        return lines

    lines = []
    for para in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if not para.strip():
            lines.append('')
            continue
        lines.extend(_split(para, page_w - 2 * margin))
    per = max(1, (page_h - 2 * margin) // line_h)

    doc = fitz.open()
    try:
        for i in range(0, len(lines), per):
            page = doc.new_page(width=page_w, height=page_h)
            page.insert_textbox(fitz.Rect(margin, margin, page_w - margin, page_h - margin),
                                '\n'.join(lines[i:i + per]),
                                fontname='china-s', fontsize=fontsize, lineheight=1.2)
        if doc.page_count == 0:
            doc.new_page(width=page_w, height=page_h)
        doc.save(out_pdf, deflate=True)
    finally:
        doc.close()


def export_to_pdf(src, out_pdf, dpi=200):
    """
    把任意受支持的文件转换成 PDF 并保存到 out_pdf。
    PDF 直接复制；Office 走 COM 导出；图片合成 PDF；TXT 转文本 PDF。
    """
    src = str(src)
    out_pdf = str(out_pdf)
    ext = Path(src).suffix.lower()
    if ext == '.pdf':
        shutil.copyfile(src, out_pdf)
        return out_pdf
    if ext in _OFFICE_EXTS:
        tmp = _office_to_pdf(src)
        try:
            shutil.copyfile(tmp, out_pdf)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
        return out_pdf
    if ext in _IMAGE_EXTS:
        _export_images_to_pdf(src, out_pdf, dpi)
        return out_pdf
    if ext == '.txt':
        _export_text_to_pdf(src, out_pdf)
        return out_pdf
    raise UnsupportedFormatError(ext)


def merge_pdfs(pdf_paths, out_pdf):
    """把多个 PDF 按顺序合并成一个"""
    fitz = _fitz()
    doc = fitz.open()
    try:
        for p in pdf_paths:
            d = fitz.open(str(p))
            try:
                doc.insert_pdf(d)
            finally:
                d.close()
        doc.save(str(out_pdf), deflate=True)
    finally:
        doc.close()
