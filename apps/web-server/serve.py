#!/usr/bin/env python3
"""
apps/web-server/serve.py — 实现 2：网页客户端 + Python 编码服务

职责边界（和静态版、打印服务严格分开）：
  · 本进程**只做编码**（文字渲染 / 抖动 / BMP / 封 AA 帧），不连接任何蓝牙设备
  · 蓝牙由浏览器（Web Bluetooth）持有，页面调本服务的 /api/* 拿帧
  · 只监听 127.0.0.1：Web Bluetooth 要求安全上下文，页面必须从 localhost 打开

启动：
    python3 apps/web-server/serve.py            # 默认 127.0.0.1:8000
    python3 apps/web-server/serve.py --port 8080

接口：
    GET  /                    页面（本目录 index.html + vendor/*）
    GET  /api/health          {ok, version, pil, width}
    POST /api/preview         返回抖动后的 PNG（所见即所得）
    POST /api/encode          返回 {"frames": [b64...], "meta": {...}}
    POST /api/calibration     校准图
    POST /api/size-probe      字号档位测试（四行 tier=0..3 + 一行位图对照）
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from memobird_printer import packet                      # noqa: E402
from memobird_printer.image import (                     # noqa: E402
    dither_to_raw, prepare, raw_to_bmp,
)

WEB_DIR = HERE
VERSION = "2.0.0"

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


def encode_size_probe(req: dict) -> dict:
    """
    字号档位测试：同一句话用 tag 0x10 = 0/1/2/3 各打一行，最后附一行位图 40px 作对照。
    用来确认「GT1 到底认不认固件字号档位」——一次打印就能看出来。
    """
    from memobird_printer.image import dither_to_raw, raw_to_bmp

    frames: list[str] = []
    for tier in range(4):
        job = packet.job_for_text(f"档位 tier={tier}\n", encoding="gbk", font_size=tier)
        frames += [base64.b64encode(f).decode() for f in job.frames]

    # 对照：位图 40px（这条路一定能变字号）
    img = prepare("位图 40px 对照", font_size=40)
    w, h, raw = dither_to_raw(img, "threshold")
    bmp = raw_to_bmp(w, h, raw, official=True)
    bmp_job = packet.build_bmp_job(bmp)
    frames += [base64.b64encode(f).decode() for f in bmp_job.frames]
    frames += [base64.b64encode(f).decode() for f in packet.feed_job(3).frames]

    return {
        "frames": frames,
        "meta": {"format": "probe", "chunks": len(frames), "bytes": len(bmp),
                 "preheat": packet.PREHEAT, "width": 384, "height": h},
    }


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
        bmp = raw_to_bmp(w, h, raw, official=True)
        job = packet.build_bmp_job(bmp)
        used, n = "bmp", len(bmp)
    frames = [base64.b64encode(f).decode() for f in job.frames]
    if req.get("feed", True):
        frames += [base64.b64encode(f).decode() for f in packet.feed_job(3).frames]
    return {
        "frames": frames,
        "meta": {"format": used, "chunks": job.chunks, "bytes": n,
                 "preheat": packet.PREHEAT, "width": w, "height": h},
    }


def encode_feed(req: dict) -> dict:
    """走纸：{"mm": 20}（精确，白图按点数）或 {"lines": 3}（粗，换行）。"""
    from memobird_printer.paper import blank_frames, line_frames

    if req.get("mm") is not None:
        frames, meta = blank_frames(mm=float(req["mm"]), dpi=int(req.get("dpi") or 203),
                                    tick=bool(req.get("tick", True)))
    else:
        frames, meta = line_frames(int(req.get("lines") or 3))
    return {"frames": [base64.b64encode(f).decode() for f in frames], "meta": meta}


def _render(req: dict):
    """把请求渲染成 (w, h, raw1bpp)。"""
    from PIL import Image

    mode = req.get("mode") or "threshold"
    invert = bool(req.get("invert"))
    width = int(req.get("width") or 384)
    darken = int(req.get("darken") or 0)

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
    return dither_to_raw(img, mode, darken=darken)


def _vflip(h: int, raw: bytes, row_bytes: int) -> bytes:
    rows = [raw[i * row_bytes:(i + 1) * row_bytes] for i in range(h)]
    return b"".join(reversed(rows))


def _size_tier(font_size) -> int:
    """把像素字号映射成固件字号档位（tag 0x10）：≤26→0 普通 / ≤36→1 大 / 更大→2。"""
    try:
        px = int(font_size or 26)
    except (TypeError, ValueError):
        px = 26
    if px <= 26:
        return 0
    if px <= 36:
        return 1
    return 2


def encode(req: dict) -> dict:
    kind = req.get("kind") or "text"
    fmt = (req.get("format") or "").lower()
    tier = _size_tier(req.get("fontSize"))
    darken = int(req.get("darken") or 0)

    # GBK 文本帧由固件自己渲染：浓度改不了它，字号档位 GT1 也不认。
    # 所以只要用户动了字号或浓度，就自动走位图（这条路一定能生效）。
    if kind == "text" and fmt in ("", "gbk") and (darken > 0 or tier > 0):
        fmt = "bmp"

    # ---- 文本：优先走 GBK 文本帧（体积最小、最快） ----
    if kind == "text" and fmt in ("", "gbk"):
        text = req.get("text") or ""
        try:
            job = packet.job_for_text(
                text, encoding="gbk",
                bold=bool(req.get("bold")),
                underline=bool(req.get("underline")),
                font_size=tier,
            )
            frames = [base64.b64encode(f).decode() for f in job.frames]
            if req.get("feed"):
                frames += [base64.b64encode(f).decode() for f in packet.feed_job(3).frames]
            return {
                "frames": frames,
                "meta": {"format": "gbk", "chunks": job.chunks, "bytes": job.total_bytes,
                         "preheat": packet.PREHEAT, "width": 384, "height": 0,
                         "sizeTier": tier, "bold": bool(req.get("bold")),
                         "underline": bool(req.get("underline"))},
            }
        except UnicodeEncodeError:
            fmt = "bmp"        # 有 GBK 以外的字符 → 自动退回图片模式

    # ---- 图片（或文本转图片） ----
    w, h, raw = _render(req)
    row_bytes = (w + 7) // 8
    if req.get("vflip"):
        raw = _vflip(h, raw, row_bytes)

    # 裸位图帧 GT1 不认（没有 BMP 头，固件不知道尺寸），已从界面移除；
    # 这里保留降级路径，避免老请求打到不支持的格式上。
    if fmt == "raw":
        fmt = "bmp"

    # official=True：与官方 SDK 一致（biHeight 正 + 行序 top-down），GT1 只认这个
    bmp = raw_to_bmp(w, h, raw, official=True)
    job = packet.build_bmp_job(bmp)
    payload_bytes = len(bmp)
    used = "bmp"

    frames = [base64.b64encode(f).decode() for f in job.frames]
    if req.get("feed"):
        frames += [base64.b64encode(f).decode() for f in packet.feed_job(3).frames]

    return {
        "frames": frames,
        "meta": {"format": used, "chunks": job.chunks, "bytes": payload_bytes,
                 "preheat": packet.PREHEAT, "width": w, "height": h,
                 "sizeTier": tier, "darken": darken},
    }


# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = f"memobird-web-server/{VERSION}"

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
            if path == "/api/feed":
                self._json(200, encode_feed(body))
                return
            if path == "/api/size-probe":
                self._json(200, encode_size_probe(body))
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
