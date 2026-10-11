# -*- coding: utf-8 -*-
"""
共享打印 · 桌面助手 v2.0（WebPrint Desktop）
独立桌面应用：本地内嵌 HTTP 服务 + 系统 WebView2 渲染网页级界面。
不依赖浏览器，打包为单文件 exe 后无需 Python 环境。
"""
import base64, json, os, sys, threading, uuid, time
import urllib.request, urllib.error, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "共享打印 · 桌面助手"
APP_VERSION = "2.0"


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def ui_path():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "ui.html")
    return os.path.join(base_dir(), "ui.html")


CONF_PATH = os.path.join(base_dir(), "config.json")


def load_conf():
    try:
        with open(CONF_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_conf(server, pin):
    try:
        with open(CONF_PATH, "w", encoding="utf-8") as f:
            json.dump({"server": server, "pin": pin}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("save conf err:", e)


# ---------------------------------------------------------------- 转发到打印服务器
def api_base(server):
    s = (server or "").strip()
    if not s:
        return ""
    if not s.startswith("http"):
        s = "http://" + s
    return s.rstrip("/")


def req(method, url, headers=None, data=None, timeout=30):
    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode("utf-8")


def jreq(method, url, headers=None, data=None, timeout=30):
    code, body = req(method, url, headers, data, timeout)
    try:
        return code, json.loads(body.decode("utf-8"))
    except Exception:
        return code, {"ok": False, "error": "HTTP %d" % code}


def srv_headers(pin):
    h = {"User-Agent": "webprint-desktop/%s" % APP_VERSION}
    if pin:
        h["X-Print-Pin"] = pin
    return h


def build_multipart(fields, files):
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


# ---------------------------------------------------------------- 状态
G = {"server": "", "pin": "", "connected": False, "info": None, "lock": threading.Lock()}
DL = {"state": "idle", "path": "", "error": ""}


# ---------------------------------------------------------------- 本地 HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            try:
                with open(ui_path(), "rb") as f:
                    html = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return
            except Exception as e:
                self._json(500, {"ok": False, "error": "UI 文件缺失：%s" % e})
                return
        if path == "/api/state":
            self._json(200, {"server": G["server"], "connected": G["connected"],
                             "has_pin": bool(G["pin"]), "version": APP_VERSION})
            return
        if path == "/api/dl-status":
            self._json(200, DL)
            return
        if path == "/api/printers":
            if not G["connected"]:
                self._json(200, {"ok": False, "error": "未连接服务器"})
                return
            code, obj = jreq("GET", api_base(G["server"]) + "/api/printers",
                             headers=srv_headers(G["pin"]), timeout=8)
            self._json(code if code == 200 else 502, obj)
            return
        if path == "/api/pdf-outputs":
            if not G["connected"]:
                self._json(200, {"ok": False, "error": "未连接服务器"})
                return
            code, obj = jreq("GET", api_base(G["server"]) + "/api/pdf-outputs",
                             headers=srv_headers(G["pin"]), timeout=10)
            self._json(code if code == 200 else 502, obj)
            return
        if path.startswith("/api/job/"):
            jid = path.rsplit("/", 1)[-1]
            code, obj = jreq("GET", api_base(G["server"]) + "/api/jobs/" + urllib.parse.quote(jid),
                             headers=srv_headers(G["pin"]), timeout=10)
            self._json(code if code == 200 else 502, obj)
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            ln = int(self.headers.get("Content-Length", 0) or 0)
        except Exception:
            ln = 0
        raw = self.rfile.read(ln) if ln else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {}

        if path == "/api/connect":
            server = (data.get("server") or "").strip()
            if not server:
                self._json(200, {"ok": False, "error": "请填写服务器地址"})
                return
            code, info = jreq("GET", api_base(server) + "/api/info", headers=srv_headers(G["pin"]), timeout=8)
            if code != 200 or not info.get("ok"):
                self._json(200, {"ok": False, "error": info.get("error", "无法连接服务器")})
                return
            if info.get("pin_required") and not G["pin"]:
                self._json(200, {"ok": False, "need_pin": True, "message": "服务器已设置访问密码，请输入 PIN"})
                return
            if info.get("pin_required"):
                code2, _ = jreq("GET", api_base(server) + "/api/printers",
                                headers=srv_headers(G["pin"]), timeout=8)
                if code2 != 200:
                    self._json(200, {"ok": False, "error": "访问密码错误"})
                    return
            with G["lock"]:
                G["server"] = server
                G["connected"] = True
                G["info"] = info
            save_conf(server, G["pin"])
            self._json(200, {"ok": True, "info": info})
            return

        if path == "/api/pin":
            pin = str(data.get("pin") or "").strip()
            with G["lock"]:
                G["pin"] = pin
            self._json(200, {"ok": True})
            return

        if path == "/api/print":
            if not G["connected"]:
                self._json(200, {"ok": False, "error": "未连接服务器"})
                return
            options = data.get("options", {})
            to_pdf = bool(data.get("to_pdf"))
            fields = {
                "to_pdf": "1" if to_pdf else "",
                "printer": options.get("printer", ""),
                "copies": str(options.get("copies", 1)),
                "orientation": options.get("orientation", "portrait"),
                "color": options.get("color", "color"),
                "duplex": options.get("duplex", "simplex"),
                "paper": options.get("paper", "A4"),
                "fit": options.get("fit", "fit"),
                "quality": options.get("quality", "standard"),
                "docname": APP_NAME,
            }
            files = []
            for f in data.get("files", []):
                try:
                    content = base64.b64decode(f.get("data", ""))
                except Exception:
                    content = b""
                files.append(("files", f.get("name", "file"), content))
            body, ctype = build_multipart(fields, files)
            h = srv_headers(G["pin"])
            h["Content-Type"] = ctype
            code, obj = jreq("POST", api_base(G["server"]) + "/api/print", headers=h, data=body, timeout=300)
            self._json(code if code == 200 else 502, obj)
            return

        if path.startswith("/api/job/"):
            parts = path.split("/")  # /api/job/<jid>/<action>
            if len(parts) >= 5:
                jid, action = parts[3], parts[4]
                code, obj = jreq("POST", api_base(G["server"]) + "/api/jobs/%s/%s"
                                 % (urllib.parse.quote(jid), action),
                                 headers=srv_headers(G["pin"]), data=b"", timeout=10)
                self._json(code if code == 200 else 502, obj)
                return

        if path == "/api/download":
            name = str(data.get("name") or "")
            if not name:
                self._json(200, {"ok": False, "error": "缺少文件名"})
                return
            DL.update(state="saving", path="", error="")
            threading.Thread(target=self._dl, args=(name,), daemon=True).start()
            self._json(200, {"ok": True, "message": "正在弹出保存窗口…"})
            return

        self._json(404, {"ok": False, "error": "not found"})

    def _dl(self, name):
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            target = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=name,
                                                  filetypes=[("PDF 文件", "*.pdf")],
                                                  title="保存 PDF 到本机")
            root.destroy()
            if not target:
                DL.update(state="idle", error="已取消")
                return
            code, body = req("GET", api_base(G["server"]) + "/download/" + urllib.parse.quote(name),
                             headers=srv_headers(G["pin"]), timeout=300)
            if code != 200:
                DL.update(state="idle", error="下载失败（HTTP %d）" % code)
                return
            with open(target, "wb") as f:
                f.write(body)
            DL.update(state="done", path=target, error="")
        except Exception as e:
            DL.update(state="idle", error="下载失败：%s" % e)


# ---------------------------------------------------------------- 入口
def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    if "--no-gui" in sys.argv:
        print("LOCAL_PORT %d" % port)
        while True:
            time.sleep(3600)
        return

    cfg = load_conf()
    with G["lock"]:
        G["server"] = cfg.get("server", "")
        G["pin"] = cfg.get("pin", "")

    import webview
    webview.create_window(APP_NAME + "  v" + APP_VERSION,
                          "http://127.0.0.1:%d/" % port,
                          width=1000, height=800, min_size=(900, 720),
                          background_color="#F2F4F8")
    webview.start()


if __name__ == "__main__":
    main()
