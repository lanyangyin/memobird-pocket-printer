#!/usr/bin/env python3
"""
phone/serve.py — 手机端（Termux proot Ubuntu）本地服务

作用：把 Python 这套编码引擎（文字渲染 / 抖动 / BMP / 蓝牙帧）包成一个本地 HTTP 服务，
      手机浏览器打开 http://127.0.0.1:8000 后，用 **Web Bluetooth** 直接把帧写进打印机。
      这样 Termux 里完全不需要 BlueZ / root：蓝牙部分由 Chrome 的 GATT 完成。

启动：
    python3 phone/serve.py            # 默认 127.0.0.1:8000
    python3 phone/serve.py --port 8080 --host 0.0.0.0

接口：
    GET  /                      网页
    GET  /api/health            {ok, pil, version}
    POST /api/preview           返回抖动后的 PNG（所见即所得）
    POST /api/encode            返回 {"frames": [b64...], "meta": {...}}

    POST body 形如：
        {"kind":"text",  "text":"你好", "fontSize":24, "mode":"threshold", "format":"gbk"|"image"}
        {"kind":"image", "dataUrl":"data:image/png;base64,...", "mode":"floyd", "format":"bmp"|"raw", "vflip":false}
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from memobird_printer import packet                      # noqa: E402
from memobird_printer.image import (                     # noqa: E402
    dither_to_raw, prepare, raw_to_bmp, preview,
)

WEB_DIR = os.path.join(ROOT, "web")
VERSION = "1.1.0"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}


# --------------------------------------------------------------------------- #
def _load_image(data_url: str):
    from io import BytesIO
    from PIL import Image

    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    return Image.open(BytesIO(base64.b64decode(data_url)))


def calibration_image():
    """校准图：用来判断上下/左右方向、分辨率、有无丢行。"""
    from PIL import Image, ImageDraw

    W, H = 384, 320
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    from memobird_printer.image import find_font

    small = find_font(size=16)
    big = find_font(size=28)

    # 左上角黑方块：判断方向的第一眼
    d.rectangle([2, 2, 42, 42], fill=0)
    d.text((50, 6), "TOP 上", font=big, fill=0)
    d.text((50, 38), "左上应为黑块", font=small, fill=0)

    # 左对齐的阶梯条：判断是否左右镜像 / 行对齐
    for i in range(8):
        y = 76 + i * 18
        d.rectangle([0, y, 24 * (i + 1), y + 8], fill=0)
        d.text((240, y - 4), f"row {i + 1}", font=small, fill=0)

    # 右侧虚线：判断列方向
    for y in range(70, 230, 8):
        d.line([370, y, 380, y], fill=0, width=3)

    # 底部
    d.text((2, 250), "BOTTOM 下 / 384 dots", font=big, fill=0)
    d.text((2, 288), "1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0", font=small, fill=0)
    return img


def encode_calibration(req: dict) -> dict:
    from memobird_printer.image import dither_to_raw, raw_to_bmp

    img = calibration_image()
    w, h, raw = dither_to_raw(img, "threshold")
    fmt = (req.get("format") or "bmp").lower()
    if req.get("vflip"):
        row_bytes = (w + 7) // 8
        raw = _vflip(h, raw, row_bytes)
    if fmt == "raw":
        job = packet.build_bitmap_job(raw)
        used, n = "raw", len(raw)
    else:
        bmp = raw_to_bmp(w, h, raw, top_down=not req.get("vflip"))
        job = packet.build_bmp_job(bmp)
        used, n = "bmp", len(bmp)
    return {
        "frames": [base64.b64encode(f).decode() for f in job.frames],
        "meta": {"format": used, "chunks": job.chunks, "bytes": n,
                 "preheat": packet.PREHEAT, "width": w, "height": h},
    }


def _render(req: dict):
    """把请求渲染成 (w, h, raw1bpp)。"""
    from PIL import Image

    mode = req.get("mode") or "threshold"
    invert = bool(req.get("invert"))
    width = int(req.get("width") or 384)

    if req.get("kind") == "image" and req.get("dataUrl"):
        img = prepare(_load_image(req["dataUrl"]), mode=mode, width=width, invert=invert)
    else:
        img = prepare(
            req.get("text") or "",
            mode=mode, width=width,
            font=req.get("font") or None,
            font_size=int(req.get("fontSize") or 24),
            invert=invert,
        )
    return dither_to_raw(img, mode)


def _vflip(h: int, raw: bytes, row_bytes: int) -> bytes:
    rows = [raw[i * row_bytes:(i + 1) * row_bytes] for i in range(h)]
    return b"".join(reversed(rows))


def encode(req: dict) -> dict:
    kind = req.get("kind") or "text"
    fmt = (req.get("format") or "").lower()

    # ---- 文本：优先走 GBK 文本帧（体积最小、最快） ----
    if kind == "text" and fmt in ("", "gbk"):
        text = req.get("text") or ""
        try:
            job = packet.job_for_text(text, encoding="gbk")
            return {
                "frames": [base64.b64encode(f).decode() for f in job.frames],
                "meta": {"format": "gbk", "chunks": job.chunks, "bytes": job.total_bytes,
                         "preheat": packet.PREHEAT, "width": 384, "height": 0},
            }
        except UnicodeEncodeError:
            fmt = "bmp"        # 有 GBK 以外的字符 → 自动退回图片模式

    # ---- 图片（或文本转图片） ----
    w, h, raw = _render(req)
    row_bytes = (w + 7) // 8
    if req.get("vflip"):
        raw = _vflip(h, raw, row_bytes)

    if fmt == "raw":
        job = packet.build_bitmap_job(raw)
        payload_bytes = len(raw)
        used = "raw"
    else:
        bmp = raw_to_bmp(w, h, raw, top_down=not req.get("vflip"))
        job = packet.build_bmp_job(bmp)
        payload_bytes = len(bmp)
        used = "bmp"

    return {
        "frames": [base64.b64encode(f).decode() for f in job.frames],
        "meta": {"format": used, "chunks": job.chunks, "bytes": payload_bytes,
                 "preheat": packet.PREHEAT, "width": w, "height": h},
    }


# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = f"memobird-phone/{VERSION}"

    def log_message(self, fmt, *args):           # 安静点，只留错误
        if args and str(args[0]).startswith(("4", "5")):
            sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ------------------------------------------------------------------ #
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8", "replace"))

    # ------------------------------------------------------------------ #
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            try:
                import PIL  # noqa: F401
                pil = True
            except ImportError:
                pil = False
            self._json(200, {"ok": True, "version": VERSION, "pil": pil,
                             "protocols": ["ble"], "width": 384})
            return
        self._static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/encode":
                self._json(200, encode(body))
                return
            if path == "/api/preview":
                w, h, raw = _render(body)
                from memobird_printer.image import _raw_to_1bit
                im = _raw_to_1bit(w, h, raw).convert("L")
                buf = __import__("io").BytesIO()
                im.save(buf, format="PNG")
                self._send(200, buf.getvalue(), "image/png")
                return
            if path == "/api/calibration":
                self._json(200, encode_calibration(body))
                return
            self._json(404, {"error": "no such api"})
        except Exception as exc:                                    # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    # ------------------------------------------------------------------ #
    def _static(self, path: str):
        if path in ("/", ""):
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("\\/")
        full = os.path.join(WEB_DIR, safe)
        if not os.path.abspath(full).startswith(WEB_DIR) or not os.path.isfile(full):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="手机端本地服务：网页 + 编码 API")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"memobird phone server {VERSION}")
    print(f"  打开： {url}")
    print("  注意：Web Bluetooth 只在 **安全上下文** 下可用，")
    print("        所以务必用 127.0.0.1/localhost 打开（不要用局域网 IP）。")
    print("  停止： Ctrl-C")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
