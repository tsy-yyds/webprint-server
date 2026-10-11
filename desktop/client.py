# -*- coding: utf-8 -*-
"""
共享打印 · 电脑客户端（独立桌面应用，不依赖浏览器）
纯标准库实现：tkinter + urllib + json + configparser，零第三方依赖。
通过 HTTP API 调用打印电脑上的「共享打印服务」。
"""
import json
import os
import sys
import uuid
import time
import threading
import configparser
import urllib.request
import urllib.error
import urllib.parse
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

APP_NAME = "共享打印 · 电脑客户端"
APP_VERSION = "1.0"

# ---------------------------------------------------------------- 配置
def conf_path():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "config.ini")


def load_conf():
    cfg = configparser.ConfigParser()
    p = conf_path()
    data = {"server": "", "pin": ""}
    try:
        if os.path.exists(p):
            cfg.read(p, encoding="utf-8")
            data["server"] = cfg.get("client", "server", fallback="").strip()
            data["pin"] = cfg.get("client", "pin", fallback="").strip()
    except Exception:
        pass
    return data


def save_conf(server, pin):
    cfg = configparser.ConfigParser()
    cfg["client"] = {"server": server, "pin": pin}
    try:
        with open(conf_path(), "w", encoding="utf-8") as f:
            cfg.write(f)
    except Exception as e:
        print("保存配置失败:", e)


# ---------------------------------------------------------------- HTTP
def _req(method, url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.getcode(), resp.read()


def _json(method, url, headers=None, data=None, timeout=30):
    code, body = _req(method, url, headers=headers, data=data, timeout=timeout)
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        obj = {"ok": False, "error": "服务器返回了无法解析的内容（HTTP %d）" % code}
    return code, obj


def build_multipart(fields, files):
    """构造 multipart/form-data 请求体。fields: dict；files: [(field, filename, bytes)]"""
    boundary = uuid.uuid4().hex
    lines = []
    for k, v in fields.items():
        lines.append(("--%s" % boundary).encode("utf-8"))
        lines.append(('Content-Disposition: form-data; name="%s"' % k).encode("utf-8"))
        lines.append(b"")
        lines.append(str(v).encode("utf-8"))
    for field, fname, content in files:
        lines.append(("--%s" % boundary).encode("utf-8"))
        lines.append(('Content-Disposition: form-data; name="%s"; filename="%s"'
                      % (field, fname.replace('"', ""))).encode("utf-8"))
        lines.append(b"Content-Type: application/octet-stream")
        lines.append(b"")
        lines.append(content)
    lines.append(("--%s--" % boundary).encode("utf-8"))
    lines.append(b"")
    return b"\r\n".join(lines), "multipart/form-data; boundary=%s" % boundary


def api_base(server):
    s = (server or "").strip()
    if not s:
        return ""
    if not s.startswith("http"):
        s = "http://" + s
    return s.rstrip("/")


class Client:
    def __init__(self, server, pin, on_result):
        self.server = server
        self.pin = pin
        self.on_result = on_result  # callable(done: bool, message: str)

    def headers(self):
        h = {"User-Agent": "webprint-desktop/%s" % APP_VERSION}
        if self.pin:
            h["X-Print-Pin"] = self.pin
        return h

    def info(self):
        base = api_base(self.server)
        if not base:
            return {"ok": False, "error": "请先填写服务器地址"}
        try:
            code, obj = _json("GET", base + "/api/info", headers=self.headers(), timeout=8)
            return obj if code == 200 else {"ok": False, "error": obj.get("error", "HTTP %d" % code)}
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": "HTTP %d" % e.code}
        except Exception as e:
            return {"ok": False, "error": "无法连接服务器：%s" % e}

    def printers(self):
        base = api_base(self.server)
        try:
            code, obj = _json("GET", base + "/api/printers", headers=self.headers(), timeout=8)
            return obj if code == 200 else {"ok": False, "error": obj.get("error", "HTTP %d" % code)}
        except Exception as e:
            return {"ok": False, "error": "获取打印机失败：%s" % e}

    def print_files(self, paths, options, to_pdf):
        base = api_base(self.server)
        files = []
        for p in paths:
            with open(p, "rb") as f:
                files.append(("files", os.path.basename(p), f.read()))
        fields = {
            "to_pdf": "1" if to_pdf else "",
            "printer": options["printer"],
            "copies": options["copies"],
            "orientation": options["orientation"],
            "color": options["color"],
            "duplex": options["duplex"],
            "paper": options["paper"],
            "fit": options["fit"],
            "quality": options["quality"],
            "docname": APP_NAME,
        }
        body, ctype = build_multipart(fields, files)
        h = self.headers()
        h["Content-Type"] = ctype
        try:
            code, obj = _json("POST", base + "/api/print", headers=h, data=body, timeout=120)
            return obj if code == 200 else {"ok": False, "error": obj.get("error", "HTTP %d" % code)}
        except Exception as e:
            return {"ok": False, "error": "提交失败：%s" % e}

    def job(self, jid):
        base = api_base(self.server)
        try:
            code, obj = _json("GET", base + "/api/jobs/%s" % jid, headers=self.headers(), timeout=10)
            return obj if code == 200 else {"ok": False, "error": obj.get("error", "HTTP %d" % code)}
        except Exception as e:
            return {"ok": False, "error": "查询任务失败：%s" % e}

    def job_action(self, jid, action):
        base = api_base(self.server)
        try:
            code, obj = _json("POST", base + "/api/jobs/%s/%s" % (jid, action),
                              headers=self.headers(), data=b"", timeout=10)
            return obj if code == 200 else {"ok": False, "error": obj.get("error", "HTTP %d" % code)}
        except Exception as e:
            return {"ok": False, "error": "操作失败：%s" % e}

    def pdf_outputs(self):
        base = api_base(self.server)
        try:
            code, obj = _json("GET", base + "/api/pdf-outputs", headers=self.headers(), timeout=10)
            return obj if code == 200 else {"ok": False, "error": obj.get("error", "HTTP %d" % code)}
        except Exception as e:
            return {"ok": False, "error": "获取 PDF 列表失败：%s" % e}

    def download_pdf(self, fname, target):
        base = api_base(self.server)
        url = base + "/download/" + urllib.parse.quote(fname)
        try:
            code, body = _req("GET", url, headers=self.headers(), timeout=120)
            if code != 200:
                return False, "下载失败（HTTP %d）" % code
            with open(target, "wb") as f:
                f.write(body)
            return True, target
        except Exception as e:
            return False, "下载失败：%s" % e


# ---------------------------------------------------------------- UI
class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_conf()
        self.client = None
        self.connected = False
        self.pin = self.cfg["pin"]
        self.server = self.cfg["server"]
        self.files = []
        self.job_polling = False

        root.title(APP_NAME + " v" + APP_VERSION)
        root.geometry("760x680")
        root.minsize(680, 600)
        try:
            root.iconbitmap(default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico"))
        except Exception:
            pass
        self._build_ui()
        self.auto_connect()

    # ---------------- UI 构建
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}
        # 顶栏：服务器 + 连接
        top = ttk.Frame(self.root)
        top.pack(fill="x", pady=(10, 0))
        ttk.Label(top, text="服务器地址").pack(side="left", padx=(10, 4))
        self.var_server = tk.StringVar(value=self.server)
        ent = ttk.Entry(top, textvariable=self.var_server, width=34)
        ent.pack(side="left")
        self.btn_conn = ttk.Button(top, text="连接", command=self.do_connect)
        self.btn_conn.pack(side="left", padx=6)
        self.lbl_status = tk.Label(top, text="● 未连接", fg="#C0392B", font=("Microsoft YaHei", 9, "bold"))
        self.lbl_status.pack(side="left", padx=8)

        # 文件区
        frm = ttk.LabelFrame(self.root, text=" 1. 选择文件 ")
        frm.pack(fill="x", pady=8, padx=10)
        self.file_list = tk.Listbox(frm, height=5, font=("Microsoft YaHei", 10))
        self.file_list.pack(fill="x", padx=8, pady=6)
        btns = ttk.Frame(frm)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="+ 添加文件", command=self.add_files).pack(side="left")
        ttk.Button(btns, text="- 移除选中", command=self.remove_files).pack(side="left", padx=6)
        ttk.Button(btns, text="清空", command=self.clear_files).pack(side="left")

        # 参数区
        par = ttk.LabelFrame(self.root, text=" 2. 打印方式 ")
        par.pack(fill="x", pady=8, padx=10)
        grid = ttk.Frame(par)
        grid.pack(fill="x", padx=8, pady=6)

        def row(r, label, widget):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=3)
            widget.grid(row=r, column=1, sticky="w", pady=3)

        self.var_mode = tk.StringVar(value="paper")
        mf = ttk.Frame(grid)
        ttk.Radiobutton(mf, text="打印到纸", variable=self.var_mode, value="paper",
                        command=self.set_mode).pack(side="left")
        ttk.Radiobutton(mf, text="打印到 PDF（存服务器）", variable=self.var_mode, value="pdf",
                        command=self.set_mode).pack(side="left", padx=8)
        row(0, "输出方式", mf)

        self.var_printer = tk.StringVar()
        self.cmb_printer = ttk.Combobox(grid, textvariable=self.var_printer, width=34, state="readonly")
        self.cmb_printer.set("（先连接服务器，自动获取打印机）")
        row(1, "打印机", self.cmb_printer)

        pf = ttk.Frame(grid)
        self.var_copies = tk.IntVar(value=1)
        ttk.Spinbox(pf, from_=1, to=99, textvariable=self.var_copies, width=5).pack(side="left")
        ttk.Label(pf, text="份").pack(side="left", padx=(4, 14))
        self.var_orient = tk.StringVar(value="纵向")
        ttk.Combobox(pf, textvariable=self.var_orient, values=("纵向", "横向"), width=7, state="readonly").pack(side="left")
        ttk.Label(pf, text="方向").pack(side="left", padx=(4, 14))
        self.var_color = tk.StringVar(value="彩色")
        ttk.Combobox(pf, textvariable=self.var_color, values=("彩色", "黑白"), width=6, state="readonly").pack(side="left")
        ttk.Label(pf, text="颜色").pack(side="left", padx=4)
        row(2, "份数/方向/颜色", pf)

        sf = ttk.Frame(grid)
        self.var_paper = tk.StringVar(value="A4")
        ttk.Combobox(sf, textvariable=self.var_paper, values=("A4", "A5", "A6", "B4", "B5", "Letter", "Legal", "Executive", "A3"),
                     width=9, state="readonly").pack(side="left")
        ttk.Label(sf, text="纸张").pack(side="left", padx=(4, 14))
        self.var_duplex = tk.StringVar(value="单面")
        ttk.Combobox(sf, textvariable=self.var_duplex, values=("单面", "手动双面"), width=8, state="readonly").pack(side="left")
        ttk.Label(sf, text="双面").pack(side="left", padx=(4, 14))
        self.var_fit = tk.StringVar(value="适应页面")
        ttk.Combobox(sf, textvariable=self.var_fit, values=("适应页面", "原始大小", "拉伸铺满"), width=10, state="readonly").pack(side="left")
        ttk.Label(sf, text="缩放").pack(side="left", padx=4)
        row(3, "纸张/双面/缩放", sf)

        qf = ttk.Frame(grid)
        self.var_quality = tk.StringVar(value="标准")
        ttk.Combobox(qf, textvariable=self.var_quality, values=("草稿", "标准", "高清"), width=7, state="readonly").pack(side="left")
        ttk.Label(qf, text="质量").pack(side="left", padx=4)
        row(4, "质量", qf)

        # 打印按钮
        act = ttk.Frame(self.root)
        act.pack(fill="x", padx=10, pady=6)
        self.btn_print = ttk.Button(act, text="开始打印", command=self.start_print)
        self.btn_print.pack(side="left", ipadx=16, ipady=4)
        self.btn_pdf = ttk.Button(act, text="转换为 PDF", command=self.start_print)
        self.btn_pdf.pack(side="left", padx=10, ipadx=16, ipady=4)
        self.btn_pdf_off = False

        # 状态区
        st = ttk.LabelFrame(self.root, text=" 3. 状态 ")
        st.pack(fill="both", expand=True, padx=10, pady=8)
        self.log = tk.Text(st, height=7, font=("Microsoft YaHei", 9), state="disabled",
                           bg="#F7F8FA", fg="#24292F")
        self.log.pack(fill="both", expand=True, padx=8, pady=6)

        # PDF 输出区
        po = ttk.LabelFrame(self.root, text=" 4. 服务器 PDF 输出（打印到 PDF 的结果，可下载到本机） ")
        po.pack(fill="x", padx=10, pady=(0, 10))
        pfrm = ttk.Frame(po)
        pfrm.pack(fill="x", padx=8, pady=6)
        self.pdf_list = tk.Listbox(pfrm, height=4, font=("Microsoft YaHei", 9))
        self.pdf_list.pack(side="left", fill="x", expand=True)
        ttk.Button(pfrm, text="刷新", command=self.refresh_pdfs).pack(side="left", padx=6)
        ttk.Button(pfrm, text="下载选中", command=self.download_pdf).pack(side="left")

        self.set_mode()

    def set_mode(self):
        # 输出方式切换：打印到 PDF 时禁用打印机选择
        is_pdf = self.var_mode.get() == "pdf"
        self.cmb_printer.configure(state="disabled" if is_pdf else "readonly")

    # ---------------- 连接
    def auto_connect(self):
        if self.server:
            threading.Thread(target=self._connect_worker, daemon=True).start()

    def do_connect(self):
        self.server = self.var_server.get().strip()
        if not self.server:
            messagebox.showwarning(APP_NAME, "请先填写服务器地址")
            return
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        self._ui(lambda: self.btn_conn.configure(state="disabled"))
        self._ui(lambda: self.lbl_status.configure(text="○ 连接中…", fg="#E67E22"))
        cli = Client(self.server, self.pin, None)
        info = cli.info()
        if not info.get("ok"):
            self._ui(lambda: self.lbl_status.configure(text="● 未连接", fg="#C0392B"))
            self._ui(lambda: self.log_line("连接失败：%s" % info.get("error", "未知错误")))
            self._ui(lambda: self.btn_conn.configure(state="normal"))
            return
        # PIN 处理
        if info.get("pin_required") and not self.pin:
            self._ui(lambda: self.prompt_pin(cli))
            return
        self._finish_connect(cli, info)

    def prompt_pin(self, cli):
        pin = simpledialog.askstring(APP_NAME, "服务器已设置访问密码，请输入 PIN：", show="*", parent=self.root)
        if pin is None:
            self._ui(lambda: self.lbl_status.configure(text="● 未连接", fg="#C0392B"))
            self._ui(lambda: self.btn_conn.configure(state="normal"))
            return
        self.pin = pin.strip()
        cli.pin = self.pin
        info = cli.info()
        if not info.get("ok"):
            self._ui(lambda: self.lbl_status.configure(text="● 未连接", fg="#C0392B"))
            self._ui(lambda: self.log_line("PIN 验证失败：%s" % info.get("error", "")))
            self._ui(lambda: self.btn_conn.configure(state="normal"))
            return
        self._finish_connect(cli, info)

    def _finish_connect(self, cli, info):
        self.client = cli
        self.connected = True
        save_conf(self.server, self.pin)
        ips = info.get("ips", [])
        self._ui(lambda: self.lbl_status.configure(text="● 已连接", fg="#0E7A4D"))
        self._ui(lambda: self.log_line("已连接服务器：%s（%s，打印服务 v%s）"
                                      % (self.server, info.get("name", ""), info.get("version", "?"))))
        if ips:
            self._ui(lambda: self.log_line("服务器本机地址：" + " / ".join(ips)))
        self._ui(lambda: self.btn_conn.configure(state="normal"))
        threading.Thread(target=self._load_printers, daemon=True).start()

    def _load_printers(self):
        if not self.client:
            return
        r = self.client.printers()
        if not r.get("ok"):
            self._ui(lambda: self.log_line("获取打印机失败：%s" % r.get("error", "")))
            return
        plist = r.get("printers", [])
        names = [p["name"] for p in plist]
        default = next((p["name"] for p in plist if p.get("is_default")), names[0] if names else "")
        self._ui(lambda: self.cmb_printer.configure(values=names))
        if default:
            self._ui(lambda: self.var_printer.set(default))
        self._ui(lambda: self.log_line("检测到 %d 台打印机：%s" % (len(names), "、".join(names) if names else "无")))
        self._ui(lambda: self.refresh_pdfs())

    # ---------------- 文件
    def add_files(self):
        if not self.connected:
            messagebox.showwarning(APP_NAME, "请先连接服务器")
            return
        paths = filedialog.askopenfilenames(
            title="选择要打印的文件",
            filetypes=[("常用文件", "*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.gif *.txt *.doc *.docx *.xls *.xlsx *.ppt *.pptx"),
                       ("所有文件", "*.*")])
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.file_list.insert("end", os.path.basename(p))

    def remove_files(self):
        sel = self.file_list.curselection()
        for i in reversed(sel):
            del self.files[i]
            self.file_list.delete(i)

    def clear_files(self):
        self.files = []
        self.file_list.delete(0, "end")

    # ---------------- 打印
    def start_print(self):
        if not self.connected or not self.client:
            messagebox.showwarning(APP_NAME, "请先连接服务器")
            return
        if not self.files:
            messagebox.showwarning(APP_NAME, "请先添加要打印的文件")
            return
        to_pdf = self.var_mode.get() == "pdf"
        printer = self.var_printer.get()
        if not to_pdf and (not printer or printer.startswith("（")):
            messagebox.showwarning(APP_NAME, "请选择打印机")
            return
        if to_pdf:
            self.btn_pdf_off = True
            self.btn_print.configure(state="disabled")
            self.btn_pdf.configure(state="disabled")
        else:
            self.btn_print.configure(state="disabled")
        options = {
            "printer": printer,
            "copies": str(max(1, min(99, self.var_copies.get()))),
            "orientation": "landscape" if self.var_orient.get() == "横向" else "portrait",
            "color": "bw" if self.var_color.get() == "黑白" else "color",
            "duplex": "manual" if self.var_duplex.get() == "手动双面" else "simplex",
            "paper": self.var_paper.get(),
            "fit": {"适应页面": "fit", "原始大小": "original", "拉伸铺满": "stretch"}[self.var_fit.get()],
            "quality": {"草稿": "draft", "标准": "standard", "高清": "high"}[self.var_quality.get()],
        }
        threading.Thread(target=self._print_worker, args=(list(self.files), options, to_pdf), daemon=True).start()

    def _print_worker(self, paths, options, to_pdf):
        mode = "打印到 PDF" if to_pdf else ("手动双面" if options["duplex"] == "manual" else "打印到纸")
        self._ui(lambda: self.log_line("▶ 开始%s，上传 %d 个文件（%s）…" % (mode, len(paths), ", ".join(os.path.basename(p) for p in paths))))
        r = self.client.print_files(paths, options, to_pdf)
        if not r.get("ok"):
            self._ui(lambda: self.log_line("提交失败：%s" % r.get("error", "")))
            self._ui(lambda: self.btn_print.configure(state="normal"))
            if self.btn_pdf_off:
                self._ui(lambda: self.btn_pdf.configure(state="normal"))
            return
        jid = r["job_id"]
        self._ui(lambda: self.log_line("任务 %s 已受理，等待服务器处理…" % jid))
        self._poll_job(jid)

    def _poll_job(self, jid):
        if self.job_polling:
            return
        self.job_polling = True
        try:
            while True:
                j = self.client.job(jid)
                if not j.get("ok"):
                    self._ui(lambda: self.log_line("查询任务失败：%s" % j.get("error", "")))
                    break
                job = j["job"]
                status = job.get("status", "")
                if status == "waiting":
                    # 手动双面：翻面提示
                    self._ui(lambda: self.show_duplex_dialog(jid))
                    break
                if status == "done":
                    files = job.get("files", [])
                    self._ui(lambda: self.log_line("✅ 任务完成，共打印/转换 %d 个文件：%s"
                                                  % (len(files), "、".join(files))))
                    break
                if status in ("failed", "cancelled"):
                    self._ui(lambda: self.log_line("任务%s：%s" % (status, job.get("error", ""))))
                    break
                time.sleep(1.5)
        finally:
            self.job_polling = False
            self._ui(lambda: self.btn_print.configure(state="normal"))
            if self.btn_pdf_off:
                self._ui(lambda: self.btn_pdf.configure(state="normal"))
                self.btn_pdf_off = False
            self._ui(lambda: self.refresh_pdfs())

    # ---------------- 手动双面弹窗
    def show_duplex_dialog(self, jid):
        win = tk.Toplevel(self.root)
        win.title("手动双面 · 请翻面")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        pad = 18
        ttk.Label(win, text="第一面已打印完成", font=("Microsoft YaHei", 14, "bold")).pack(pady=(pad, 2))
        ttk.Label(win, text="请把打印好的纸从出纸口取出，翻面后放回纸盒：", font=("Microsoft YaHei", 10)).pack()
        # 示意图：Canvas 画翻面流程
        cv = tk.Canvas(win, width=420, height=150, bg="#FAFAF6")
        cv.pack(pady=8)
        # 步骤1：纸从出纸口出来（字朝上）
        cv.create_text(70, 30, text="① 取出纸", font=("Microsoft YaHei", 9), fill="#57606A")
        cv.create_rectangle(30, 55, 110, 95, fill="#fff", outline="#1B5FBF", width=2)
        cv.create_text(70, 75, text="第 1 面", font=("Microsoft YaHei", 8), fill="#1B5FBF")
        cv.create_rectangle(70, 100, 110, 104, fill="#D5DBE0")  # 纸厚示意
        # 步骤2：翻转
        cv.create_text(210, 30, text="② 翻面（上下颠倒）", font=("Microsoft YaHei", 9), fill="#57606A")
        cv.create_arc(160, 50, 250, 100, start=90, extent=180, style="arc", outline="#E67E22", width=2)
        cv.create_rectangle(175, 55, 235, 90, fill="#fff", outline="#1B5FBF", width=2)
        cv.create_text(205, 75, text="背面朝上", font=("Microsoft YaHei", 8), fill="#E67E22")
        # 步骤3：放回
        cv.create_text(360, 30, text="③ 放回纸盒", font=("Microsoft YaHei", 9), fill="#57606A")
        cv.create_rectangle(315, 55, 405, 95, fill="#fff", outline="#1B5FBF", width=2)
        cv.create_text(360, 75, text="第 2 面", font=("Microsoft YaHei", 8), fill="#0E7A4D")
        cv.create_rectangle(315, 100, 405, 104, fill="#D5DBE0")
        ttk.Label(win, text="确认纸张方向与平时手动双面一致后，点「下一步，继续打印」",
                  font=("Microsoft YaHei", 9), foreground="#7A5A00").pack()
        btns = ttk.Frame(win)
        btns.pack(pady=pad)
        ok = ttk.Button(btns, text="下一步，继续打印", command=lambda: self._duplex_act(win, jid, "continue"))
        ok.pack(side="left", ipadx=14, ipady=3)
        cc = ttk.Button(btns, text="取消任务", command=lambda: self._duplex_act(win, jid, "cancel"))
        cc.pack(side="left", padx=10, ipadx=14, ipady=3)

    def _duplex_act(self, win, jid, action):
        threading.Thread(target=self._duplex_worker, args=(win, jid, action), daemon=True).start()

    def _duplex_worker(self, win, jid, action):
        r = self.client.job_action(jid, action)
        self._ui(lambda: win.destroy())
        if r.get("ok"):
            if action == "continue":
                self._ui(lambda: self.log_line("已确认翻面，继续打印背面…"))
                self._poll_job(jid)
            else:
                self._ui(lambda: self.log_line("任务已取消"))
        else:
            self._ui(lambda: self.log_line("操作失败：%s" % r.get("error", "")))

    # ---------------- PDF 输出
    def refresh_pdfs(self):
        if not self.connected or not self.client:
            return
        def work():
            r = self.client.pdf_outputs()
            if not r.get("ok"):
                self._ui(lambda: self.log_line("获取 PDF 列表失败：%s" % r.get("error", "")))
                return
            files = r.get("files", [])
            self._ui(lambda: self.pdf_list.delete(0, "end"))
            for f in files:
                self._ui(lambda f=f: self.pdf_list.insert("end", "%s  (%s KB)" % (f["name"], f["size"] // 1024)))
        threading.Thread(target=work, daemon=True).start()

    def download_pdf(self):
        if not self.client:
            return
        sel = self.pdf_list.curselection()
        if not sel:
            messagebox.showwarning(APP_NAME, "请先在列表中选择一个 PDF")
            return
        text = self.pdf_list.get(sel[0])
        fname = text.split("  (")[0]
        target = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=fname,
                                              filetypes=[("PDF 文件", "*.pdf")])
        if not target:
            return
        threading.Thread(target=self._download_worker, args=(fname, target), daemon=True).start()

    def _download_worker(self, fname, target):
        self._ui(lambda: self.log_line("正在下载 %s …" % fname))
        ok, msg = self.client.download_pdf(fname, target)
        self._ui(lambda: self.log_line(("✅ 已保存到 " if ok else "❌ ") + msg))

    # ---------------- 工具
    def log_line(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S ") + text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _ui(self, fn):
        self.root.after(0, fn)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
