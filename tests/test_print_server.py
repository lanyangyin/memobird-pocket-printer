#!/usr/bin/env python3
"""
tests/test_print_server.py — 打印服务（实现 3）的测试

    python tests/test_print_server.py

两层：
  1. 纯逻辑：PrintService + fake 后端，验证请求 → 帧 → "发送"的整条链
  2. HTTP：真的起一个 ThreadingHTTPServer，用 urllib 打 /health /print /status，
     并验证 API key、参数校验、错误码
不需要打印机，也不需要网络。
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "apps", "print-server"))

import server as ps                                     # noqa: E402
from memobird_printer import packet                     # noqa: E402

fails: list[str] = []
passes = 0


def check(name, cond, detail=""):
    global passes
    if cond:
        passes += 1
        print(f"  [OK ] {name}{('  ' + detail) if detail else ''}")
    else:
        fails.append(name)
        print(f"  [FAIL] {name}{('  ' + detail) if detail else ''}")


def png_data_url(w=40, h=20) -> str:
    from PIL import Image

    img = Image.new("L", (w, h), 255)
    for x in range(w):
        for y in range(h):
            if (x // 4 + y // 4) % 2 == 0:
                img.putpixel((x, y), 0)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- #
print("1) 纯逻辑：请求 → 帧")
svc = ps.PrintService("fake", "", verbose=False)

out = svc.print_request({"text": "服务器磁盘 85%"})
check("文本走 GBK 帧", out["meta"]["format"] == "gbk", str(out["meta"]["format"]))
check("含 1 帧内容 + 1 帧走纸", out["frames"] == 2, str(out["frames"]))
sent = svc.worker.sent[-1]
check("帧头是 AA", sent["frames"][0][0] == 0xAA)
check("预热度 2048", sent["preheat"] is True and packet.PREHEAT == 2048)

out2 = svc.print_request({"text": "大字号", "fontSize": 40, "darken": 2})
check("大字号/浓度 → 位图", out2["meta"]["format"] == "bmp", str(out2["meta"]["format"]))
check("位图高度 > 0", out2["meta"]["height"] > 0, f"{out2['meta']['width']}x{out2['meta']['height']}")
bmp_frame = svc.worker.sent[-1]["frames"][0]
check("首帧命令字 0x04", bmp_frame[3] == 0x04)

out3 = svc.print_request({"image": png_data_url(), "mode": "threshold"})
check("图片走位图", out3["meta"]["format"] == "bmp")
check("图片宽度补齐到 384", out3["meta"]["width"] == 384, str(out3["meta"]["width"]))

try:
    svc.print_request({"text": "   "})
    check("空文本应报错", False)
except ValueError as exc:
    check("空文本报 ValueError", "为空" in str(exc), str(exc))

check("计数累加", svc.count == 3, str(svc.count))
check("status 有 last", svc.status()["last"] is not None)

# --------------------------------------------------------------------------- #
print("\n2) HTTP：真起一个服务")
service = ps.PrintService("fake", "")
ps.Handler.service = service
ps.Handler.api_key = None
srv = ps.ThreadingHTTPServer(("127.0.0.1", 0), ps.Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"


def req(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


code, body = req("GET", "/health")
check("GET /health 200", code == 200 and body.get("ok") is True, body.get("backend", ""))

code, body = req("POST", "/print", {"text": "hello"})
check("POST /print 200", code == 200 and body.get("ok") is True)
check("返回 meta.format", body.get("meta", {}).get("format") == "gbk")

code, body = req("POST", "/print/text", {"text": "路径别名"})
check("POST /print/text 可用", code == 200)

code, body = req("POST", "/print", {"text": ""})
check("空文本 400", code == 400 and body.get("ok") is False, str(code))

code, body = req("POST", "/nope", {})
check("未知路径 404", code == 404)

code, body = req("GET", "/status")
check("GET /status 200", code == 200 and body.get("backend") == "fake")

# 缺纸预检：把 paper_state 打桩成 True，checkPaper 应该 409
orig_paper = service.paper_state
service.paper_state = lambda: True
try:
    service.print_request({"text": "x", "checkPaper": True})
    check("缺纸时 checkPaper 应拒绝", False)
except ps.PrinterNotReady as exc:
    check("缺纸时 checkPaper 拒绝", "缺纸" in str(exc), str(exc))

code, body = req("POST", "/print", {"text": "缺纸测试", "checkPaper": True})
check("缺纸 → HTTP 409", code == 409, str(code))
service.paper_state = orig_paper

# 不缺纸时照常
service.paper_state = lambda: False
code, body = req("POST", "/print", {"text": "有纸", "checkPaper": True})
check("有纸时 checkPaper 通过", code == 200, str(code))
service.paper_state = orig_paper

# 设备信息/控灯：fake 后端应该明确拒绝（而不是假装成功）
code, body = req("POST", "/feed", {"mm": 20})
check("POST /feed 200", code == 200 and body.get("ok") is True, str(code))
check("走纸 20mm = 160 点", body.get("meta", {}).get("dots") == 160, str(body.get("meta", {}).get("dots")))
check("走纸帧数 8", body.get("frames") == 8, str(body.get("frames")))
code, body = req("POST", "/feed", {"lines": 3})
check("POST /feed lines 200", code == 200 and body.get("meta", {}).get("lines") == 3)

code, body = req("GET", "/device")
check("GET /device 在 fake 下 400", code == 400 and body.get("ok") is False, str(code))
code, body = req("POST", "/device/led", {"on": True})
check("POST /device/led 在 fake 下 400", code == 400 and body.get("ok") is False, str(code))

# API key
ps.Handler.api_key = "SECRET"
code, body = req("POST", "/print", {"text": "no key"})
check("无 key → 401", code == 401, str(code))
code, body = req("POST", "/print", {"text": "with key"}, headers={"X-Api-Key": "SECRET"})
check("带 key → 200", code == 200, str(code))
code, body = req("GET", "/status?key=SECRET")
check("query key 也可用", code == 200, str(code))
ps.Handler.api_key = None

# 首页
with urllib.request.urlopen(base + "/", timeout=10) as r:
    html = r.read().decode()
check("首页有表单", "<textarea" in html and "/print" in html, f"{len(html)}B")

srv.shutdown()
srv.server_close()

# --------------------------------------------------------------------------- #
print()
if fails:
    print(f"失败 {len(fails)} 项: {fails}")
    sys.exit(1)
print(f"全部通过 ✅（{passes} 项）")
