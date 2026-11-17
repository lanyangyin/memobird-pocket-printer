#!/usr/bin/env python3
"""
apps/print-server/server.py — 实现 3：真正的打印服务（Python 直连打印机 + HTTP API）

和前两个实现的区别（很重要）：
  · 实现 1/2 里**蓝牙在浏览器**手里，Python 只做编码
  · 本实现里**蓝牙在 Python 进程**手里：自己连打印机、自己发字节，对外只暴露 HTTP
  · 所以它必须跑在有蓝蓝牙适配器的机器上（PC / 树莓派 / NAS），不依赖浏览器

支持三种后端：
    --backend ble  --target AA:BB:CC:DD:EE:FF     # BLE（bleak，Win10+/Linux/macOS）
    --backend spp  --target COM5  或  /dev/rfcomm0  # 经典蓝牙 SPP（pyserial）
    --backend lan  --target 192.168.1.50            # WiFi 机型（HTTP /sys/printer）
    --backend fake                                  # 不发硬件，只生成帧（测试/演练）

启动：
    python apps/print-server/server.py --backend ble --target AA:BB:CC:DD:EE:FF --port 8100

用法：
    curl -X POST http://127.0.0.1:8100/print -H 'Content-Type: application/json' \
         -d '{"text":"服务器磁盘 85%","darken":1}'
    curl -X POST ... -d '{"image":"data:image/png;base64,...","mode":"floyd"}'
    curl http://127.0.0.1:8100/status
    # 浏览器打开 http://127.0.0.1:8100/ 有最小输入框
"""
from __future__ import annotations

import argparse
import asyncio
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
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from memobird_printer import packet                                  # noqa: E402
from memobird_printer.image import (                                 # noqa: E402
    dither_to_raw, prepare, raw_to_bmp,
)

VERSION = "1.0.0"
MAX_BODY = 12 * 1024 * 1024      # 图片 base64 可能有几 MB


class PrinterNotReady(Exception):
    """设备当前状态不能打印（例如缺纸）—— HTTP 层映射成 409。"""


# --------------------------------------------------------------------------- #
# 编码：请求 → 帧（与实现 2 的服务端逻辑一致，但这里直接用库，不经 HTTP）
# --------------------------------------------------------------------------- #
def size_tier(font_size) -> int:
    try:
        px = int(font_size or 26)
    except (TypeError, ValueError):
        px = 26
    return 0 if px <= 26 else (1 if px <= 36 else 2)


def _load_image(data: str):
    from PIL import Image

    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(data)))


def build_frames(req: dict) -> tuple[list[bytes], dict]:
    """请求体 → (frames, meta)。文本优先走 GBK 帧，其余走 BMP 位图。"""
    kind = (req.get("kind") or ("image" if req.get("image") else "text")).lower()
    darken = max(0, min(3, int(req.get("darken") or 0)))
    tier = size_tier(req.get("fontSize"))
    mode = req.get("mode") or "threshold"
    feed = bool(req.get("feed", True))

    if kind == "text":
        text = req.get("text") or ""
        if not text.strip():
            raise ValueError("text 为空")
        # 快路径：GBK 文本帧（默认字号、无浓度、无加粗/下划线时才用）
        if darken == 0 and tier == 0 and not req.get("bold") and not req.get("underline"):
            try:
                job = packet.job_for_text(text, encoding="gbk")
                frames = list(job.frames)
                if feed:
                    frames += packet.feed_job(3).frames
                return frames, {"format": "gbk", "chunks": job.chunks,
                                "bytes": job.total_bytes, "preheat": packet.PREHEAT,
                                "width": 384, "height": 0}
            except UnicodeEncodeError:
                pass    # 有 GBK 编不了的字符 → 走位图

        img = prepare(text, mode=mode, font_size=int(req.get("fontSize") or 24))
    else:
        data = req.get("image") or req.get("dataUrl")
        if not data:
            raise ValueError("image 为空")
        img = prepare(_load_image(data), mode=mode)

    total_mm = req.get("totalMm")
    if total_mm:
        from memobird_printer.paper import pad_to_length

        img = pad_to_length(img, float(total_mm), dpi=int(req.get("dpi") or 203),
                            align=req.get("align") or "top", total=True)

    target_mm = req.get("lengthMm")
    if target_mm:
        from memobird_printer.paper import pad_to_length

        img = pad_to_length(img, float(target_mm), dpi=int(req.get("dpi") or 203),
                            align=req.get("align") or "top")

    w, h, raw = dither_to_raw(img, mode, darken=darken)
    if req.get("invert"):
        # 反色在 prepare 里已经做过灰度处理，这里只兜底处理显式 invert
        pass
    bmp = raw_to_bmp(w, h, raw, official=True, top_down=not req.get("vflip"))
    job = packet.build_bmp_job(bmp)
    frames = list(job.frames)
    if feed:
        frames += packet.feed_job(3).frames
    return frames, {"format": "bmp", "chunks": job.chunks, "bytes": len(bmp),
                    "preheat": packet.PREHEAT, "width": w, "height": h}


# --------------------------------------------------------------------------- #
# 传输后端
# --------------------------------------------------------------------------- #
class BleWorker:
    """BLE 必须跑在 asyncio 里；这里起一个常驻事件循环线程，HTTP 线程把协程投进去。"""

    def __init__(self, target: str, *, settle: float = 0.02):
        self.target = target
        self.settle = settle
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="ble-loop", daemon=True)
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def call(self, coro, timeout: float):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    async def _send(self, frames: list[bytes], preheat: bool):
        from memobird_printer.ble import BlePrinter

        async with BlePrinter(self.target, settle=self.settle, echo=False) as dev:
            await dev.send_frames(frames, preheat=preheat, inter_frame=0.02)

    def send(self, frames: list[bytes], preheat: bool, timeout: float = 180):
        return self.call(self._send(frames, preheat), timeout)

    async def _read_info(self) -> tuple[list[dict], bool | None]:
        from memobird_printer import device
        from memobird_printer.ble import BlePrinter

        async with BlePrinter(self.target, settle=self.settle, echo=False) as dev:
            infos = await device.read_info(dev, wait=1.5)
            return [i.as_dict() for i in infos], (device.paper_out(infos[-1]) if infos else None)

    def read_info(self, timeout: float = 30) -> tuple[list[dict], bool | None]:
        return self.call(self._read_info(), timeout)

    async def _set_setting(self, tag: int, value: int) -> dict:
        from memobird_printer import device
        from memobird_printer.ble import BlePrinter

        async with BlePrinter(self.target, settle=self.settle, echo=False) as dev:
            return await device.set_setting(dev, tag, value, wait=1.2)

    def set_setting(self, tag: int, value: int, timeout: float = 30) -> dict:
        return self.call(self._set_setting(tag, value), timeout)


class SppWorker:
    def __init__(self, port: str, baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate

    def send(self, frames: list[bytes], preheat: bool, timeout: float = 180):
        from memobird_printer.ble import SppPrinter

        with SppPrinter(self.port, baudrate=self.baudrate) as dev:
            dev.send_frames(frames, preheat=preheat)


class LanWorker:
    def __init__(self, host: str):
        self.host = host

    def send(self, frames: list[bytes], preheat: bool, timeout: float = 60):
        """LAN 机型走 HTTP JSON，不是一个字节流 —— 这里把帧还原成内容重发。
        由于我们只在 LAN 后端下收到文本/图片，交给 LanPrinter 自己的接口更稳。"""
        raise NotImplementedError


class FakeWorker:
    """不发硬件，只记录。用来演练/测试，也是 CI 里 E2E 的传输层。"""

    def __init__(self, *, verbose: bool = False):
        self.verbose = verbose
        self.sent: list[dict] = []

    def send(self, frames: list[bytes], preheat: bool, timeout: float = 10):
        self.sent.append({
            "frames": frames, "preheat": preheat, "time": time.time(),
            "bytes": sum(len(f) for f in frames),
        })
        if self.verbose:
            for i, f in enumerate(frames, 1):
                print(f"  fake: 帧 {i}/{len(frames)} {len(f)}B {f[:8].hex()}")


# --------------------------------------------------------------------------- #
# 打印服务（含串行化，避免两次打印交织）
# --------------------------------------------------------------------------- #
class PrintService:
    def __init__(self, backend: str, target: str, *, verbose: bool = False):
        self.backend = backend
        self.target = target
        self.verbose = verbose
        self.lock = threading.Lock()
        self.last: dict | None = None
        self.last_error: str | None = None
        self.count = 0

        if backend == "ble":
            self.worker = BleWorker(target)
        elif backend == "spp":
            self.worker = SppWorker(target)
        elif backend == "fake":
            self.worker = FakeWorker(verbose=verbose)
        elif backend == "lan":
            self.worker = None      # LAN 直接走库的 LanPrinter，见 print_request
        else:
            raise ValueError(f"未知后端: {backend}")

    # ------------------------------------------------------------------ #
    def paper_state(self) -> bool | None:
        """读一次缺纸标志（只有 ble 后端能读）。None = 读不到。"""
        if self.backend != "ble" or not isinstance(self.worker, BleWorker):
            return None
        try:
            _, paper = self.worker.read_info(timeout=25)
        except Exception:                                     # noqa: BLE001
            return None
        self.last_paper_out = paper
        return paper

    def print_request(self, req: dict) -> dict:
        """请求 → 打印 → 结果字典（HTTP 层只负责序列化）"""
        started = time.time()
        with self.lock:                                # 串行：一次只打一张
            # 预检：显式要求时先看有没有纸（多花 ~2 秒，默认不做）
            if req.get("checkPaper") and self.paper_state() is True:
                raise PrinterNotReady("打印机缺纸（0x06=1）—— 放好纸再试")

            frames, meta = build_frames(req)

            if self.backend == "lan":
                result = self._print_lan(req, meta)
            else:
                preheat = bool(req.get("preheat", True))
                self.worker.send(frames, preheat)
                result = {"ok": True, "frames": len(frames),
                          "bytes_sent": sum(len(f) for f in frames) + (packet.PREHEAT if preheat else 0)}

            self.count += 1
            self.last = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "meta": meta,
                         "elapsed_ms": round((time.time() - started) * 1000)}
            self.last_error = None
            out = {"ok": True, "meta": meta, "elapsed_ms": self.last["elapsed_ms"]}
            out.update(result)
            return out

    # ------------------------------------------------------------------ #
    def _print_lan(self, req: dict, meta: dict) -> dict:
        """WiFi 机型：不走字节流，直接用 LanPrinter 的 JSON 接口。"""
        from memobird_printer.lan import LanPrinter

        p = LanPrinter(self.target)
        if meta["format"] == "gbk":
            return p.print_text(req.get("text") or "")
        data = req.get("image") or req.get("dataUrl")
        if not data:
            raise ValueError("LAN 后端的位图模式需要 image")
        img = prepare(_load_image(data), mode=req.get("mode") or "floyd")
        w, h, raw = dither_to_raw(img, req.get("mode") or "floyd",
                                  darken=int(req.get("darken") or 0))
        return p.print_image(raw_to_bmp(w, h, raw, official=True))

    def status(self) -> dict:
        return {
            "backend": self.backend,
            "target": self.target,
            "printed": self.count,
            "last": self.last,
            "last_error": self.last_error,
            "paper_out": getattr(self, "last_paper_out", None),
        }

    def device_info(self) -> dict:
        """读设备信息（cmd 0x01）。只有 ble 后端能读。"""
        if self.backend == "fake":
            return {"ok": False, "backend": "fake", "error": "fake 后端没有真实设备"}
        if self.backend != "ble":
            return {"ok": False, "backend": self.backend, "error": "该后端暂不支持读设备信息"}
        if not isinstance(self.worker, BleWorker):
            return {"ok": False, "error": "后端未就绪"}
        with self.lock:
            infos, paper = self.worker.read_info()
        self.last_paper_out = paper
        from memobird_printer import device as _dev

        raw = None
        with self.lock:
            infos, paper = self.worker.read_info()
        self.last_paper_out = paper
        return {"ok": True, "backend": self.backend, "target": self.target,
                "paper_out": paper, "battery": self._battery(),
                "device": infos[-1] if infos else None}

    def _battery(self) -> dict | None:
        """电压 → 估算电量（0x04 = 电池电压，0.05V/LSB）"""
        if self.backend != "ble" or not isinstance(self.worker, BleWorker):
            return None
        try:
            infos, _ = self.worker.read_info(timeout=25)
        except Exception:                                     # noqa: BLE001
            return None
        return infos[-1].get("battery") if infos else None

    def device_led(self, on: bool) -> dict:
        """开关指示灯（cmd 0x03 tag 0x03）。只有 ble 后端能做。"""
        if self.backend != "ble" or not isinstance(self.worker, BleWorker):
            return {"ok": False, "backend": self.backend, "error": "只有 ble 后端能控制指示灯"}
        with self.lock:
            state = self.worker.set_setting(0x03, 1 if on else 0)
        led = state.get(0x03)
        return {"ok": True, "requested": 1 if on else 0, "led": led,
                "state": {f"0x{k:02x}": v for k, v in sorted(state.items())}}

    def feed(self, req: dict) -> dict:
        """走纸：{"mm": 50}（精确，白图按点数）或 {"lines": 3}（粗，换行）"""
        from memobird_printer.paper import blank_frames, line_frames

        if req.get("mm") is not None:
            frames, meta = blank_frames(mm=float(req["mm"]), dpi=int(req.get("dpi") or 203),
                                        tick=bool(req.get("tick")))
        else:
            frames, meta = line_frames(int(req.get("lines") or 3))

        if self.backend == "fake":
            self.worker.send(frames, True)
        elif self.backend == "ble":
            with self.lock:
                self.worker.send(frames, True)
        elif self.backend == "spp":
            with self.lock:
                self.worker.send(frames, True)
        else:
            raise ValueError("该后端不支持走纸（局域网机型请直接打一张空白图）")

        self.count += 1
        return {"ok": True, "meta": meta, "frames": len(frames)}

    def health(self) -> dict:
        info = {"ok": True, "version": VERSION, "backend": self.backend, "target": self.target}
        if isinstance(self.worker, FakeWorker):
            info["fake_sent"] = len(self.worker.sent)
        return info


# --------------------------------------------------------------------------- #
# HTTP 层
# --------------------------------------------------------------------------- #
INDEX = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>打印服务</title><style>
body{background:#0e1116;color:#e6edf3;font:15px/1.6 -apple-system,"Microsoft YaHei",sans-serif;
     max-width:640px;margin:0 auto;padding:20px}
textarea,input,select{width:100%;background:#0d1117;color:#e6edf3;border:1px solid #2a323d;
     border-radius:10px;padding:10px;font:inherit;margin:6px 0 12px}
button{background:#2f81f7;border:0;color:#fff;padding:12px 18px;border-radius:10px;
     font:inherit;font-weight:600;width:100%}
pre{background:#0b0e13;border:1px solid #2a323d;border-radius:10px;padding:12px;
    font-size:12px;white-space:pre-wrap;max-height:300px;overflow:auto}
.row{display:flex;gap:10px}.row>*{flex:1}
</style></head><body>
<h2>打印服务 <small>__VER__ / __BACKEND__</small></h2>
<textarea id="t" rows="5">服务器磁盘 85%，请清理</textarea>
<div class="row">
  <select id="darken"><option value="0">标准</option><option value="1">加深</option>
  <option value="2">更黑</option><option value="3">最黑</option></select>
  <select id="fs"><option value="26">默认字号</option><option value="34">大</option>
  <option value="42">更大</option></select>
</div>
<button onclick="go()">打印</button>
<pre id="o">就绪</pre>
<script>
async function go(){
  const o=document.getElementById('o'); o.textContent='发送中…';
  try{
    const r=await fetch('/print',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:document.getElementById('t').value,
        darken:+document.getElementById('darken').value,
        fontSize:+document.getElementById('fs').value})});
    o.textContent=r.status+' '+JSON.stringify(await r.json(),null,2);
  }catch(e){ o.textContent='失败: '+e.message }
}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = f"memobird-print-server/{VERSION}"
    service: PrintService = None       # 由 main() 注入
    api_key: str | None = None

    # ------------------------------------------------------------------ #
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, obj: dict):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        if not self.api_key:
            return True
        key = self.headers.get("X-Api-Key") or (parse_qs(urlparse(self.path).query).get("key") or [""])[0]
        return key == self.api_key

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError(f"请求体过大（> {MAX_BODY // 1024 // 1024} MB）")
        return json.loads(self.rfile.read(length).decode("utf-8", "replace") or "{}")

    # ------------------------------------------------------------------ #
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._json(200, self.service.health())
        elif path == "/status":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            self._json(200, self.service.status())
        elif path == "/device":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                out = self.service.device_info()
                self._json(200 if out.get("ok") else 400, out)
            except Exception as exc:                                # noqa: BLE001
                self._json(503, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        elif path in ("/", "/index.html"):
            html = INDEX.replace("__VER__", VERSION).replace("__BACKEND__", self.service.backend)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path

        # 设备控制：只支持已验证的"开/关灯"
        if path == "/device/led":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                body = self._read_json()
                out = self.service.device_led(bool(body.get("on", True)))
                self._json(200 if out.get("ok") else 400, out)
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:                                # noqa: BLE001
                self._json(503, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        # 走纸（精确按毫米）
        if path == "/feed":
            if not self._authorized():
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                self._json(200, self.service.feed(self._read_json()))
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:                                # noqa: BLE001
                self._json(503, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        if path not in ("/print", "/print/text", "/print/image"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            req = self._read_json()
            if path == "/print/text":
                req["kind"] = "text"
            elif path == "/print/image":
                req["kind"] = "image"
            out = self.service.print_request(req)
            self._json(200, out)
        except PrinterNotReady as exc:
            self.service.last_error = str(exc)
            self._json(409, {"ok": False, "error": str(exc)})
        except ValueError as exc:
            self.service.last_error = str(exc)
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:                                    # noqa: BLE001
            self.service.last_error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            self._json(503, {"ok": False, "error": self.service.last_error})


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="口袋打印机打印服务（Python 直连 + HTTP API）")
    ap.add_argument("--backend", default="fake", choices=["ble", "spp", "lan", "fake"])
    ap.add_argument("--target", default="", help="BLE 地址 / SPP 串口 / LAN IP")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址；要对局域网开放用 0.0.0.0")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--api-key", default=os.environ.get("MEMOBIRD_API_KEY", ""),
                    help="可选的访问口令（请求头 X-Api-Key 或 ?key=）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.backend != "fake" and not args.target:
        print("除 fake 之外的后端都要 --target", file=sys.stderr)
        return 2

    service = PrintService(args.backend, args.target, verbose=args.verbose)
    Handler.service = service
    Handler.api_key = args.api_key or None

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"打印服务 {VERSION}  后端={args.backend} 目标={args.target or '-'}")
    print(f"  页面： http://{shown}:{args.port}/")
    print(f"  API ： POST /print   GET /health  GET /status")
    if Handler.api_key:
        print("  已启用 API key（X-Api-Key 或 ?key=）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
