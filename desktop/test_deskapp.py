# -*- coding: utf-8 -*-
"""desktop_app 本地服务全链路测试：connect -> printers -> print -> job 轮询 -> pdf-outputs"""
import json, subprocess, sys, time, base64, urllib.request

# 1. 启动 --no-gui 本地服务
p = subprocess.Popen([sys.executable, r"D:\桌面\共享打印工程文件\desktop_app\app.py", "--no-gui"],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8")
line = p.stdout.readline().strip()
print("SERVER:", line)
port = int(line.split()[-1])
base = "http://127.0.0.1:%d" % port

def call(path, method="GET", data=None, timeout=60):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    r = urllib.request.Request(base + path, data=body, method=method,
                               headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

# 2. 初始状态
s = call("/api/state")
print("STATE:", s)

# 3. 连接真实打印服务器（本机 8000 端口运行中）
r = call("/api/connect", "POST", {"server": "127.0.0.1:8000"})
print("CONNECT:", r)
assert r["ok"], "connect failed: %s" % r

# 4. 打印机列表
pr = call("/api/printers")
print("PRINTERS:", [x["name"] for x in pr.get("printers", [])])
assert pr["ok"] and pr["printers"]

# 5. 构造小文件（内存 base64）打印到 PDF
pdf_bytes = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
data = base64.b64encode(pdf_bytes).decode()
r = call("/api/print", "POST", {
    "to_pdf": True,
    "options": {"printer": "", "copies": 1, "orientation": "portrait", "color": "color",
                "duplex": "simplex", "paper": "A4", "fit": "fit", "quality": "standard"},
    "files": [{"name": "desktop_test.pdf", "data": data}]
})
print("PRINT:", r)
assert r.get("job_id"), r
jid = r["job_id"]

# 6. 轮询任务
for i in range(30):
    time.sleep(1.5)
    j = call("/api/job/" + jid)
    st = j.get("job", {}).get("status")
    print("JOB %d:" % i, st)
    if st in ("done", "failed", "cancelled", "waiting"):
        break
print("JOB FINAL:", j)

# 7. PDF 输出列表
po = call("/api/pdf-outputs")
print("PDFS:", [(f["name"], f["size"]) for f in po.get("files", [])])

p.kill()
print("ALL OK")
