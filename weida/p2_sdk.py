"""用官方 JS SDK（无头 Chrome）把内容编码成 P2 能打印的字节流。

SDK 支持 `jobName = "#!#RawData#!#"`，commitJob() 直接返回打印二进制。
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_static_page import CDP, find_chrome, free_port  # noqa: E402

SDK = os.path.join(ROOT, "weida", "docs", "lpapi", "package", "libs", "index.umd.js").replace("\\", "/")

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script src="file:///__SDK__"></script>
<script>
window.__OUT__ = null; window.__ERR__ = null;
window.__RENDER__ = async function(spec) {
  try {
    const api = LPAPI.LPAPI.create({ webBLE: false, webHID: false, logLevel: 0 });
    api.startJob({ width: spec.width, height: spec.height, jobName: "#!#RawData#!#" });
    if (spec.image) {
      const img = new Image();
      await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = spec.image; });
      api.drawImage({ image: img, x: 0, y: 0, width: spec.width, height: spec.height });
    }
    const res = await api.commitJob();
    const pd = res && res.resultInfo && res.resultInfo.printData;
    const out = [];
    (function walk(x, d) {
      if (!x || d > 8) return;
      if (x instanceof Uint8Array) { for (const b of x) out.push(b); return; }
      if (Array.isArray(x)) { for (const it of x) walk(it, d + 1); return; }
      if (typeof x === "object") {
        const ks = Object.keys(x).filter(k => /^[0-9]+$/.test(k)).map(Number).sort((a,b)=>a-b);
        if (ks.length) { for (const k of ks) out.push(x[k] & 255); return; }
        for (const k of Object.keys(x)) walk(x[k], d + 1);
      }
    })(pd, 0);
    let hex = "";
    for (const b of out) hex += b.toString(16).padStart(2, "0");
    window.__OUT__ = { status: res && res.statusCode, len: out.length, hex: hex };
  } catch (e) { window.__ERR__ = String((e && e.stack) || e); }
};
</script></body></html>"""


def encode(image_data_url: str, width_mm: float = 50, height_mm: float = 30,
           timeout: float = 40.0) -> bytes:
    """把一张图片（data URL）编码成打印字节流。"""
    page = os.path.join(ROOT, "weida", "docs", f"_enc_{int(time.time()*1000)}.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(HTML.replace("__SDK__", SDK))

    chrome = find_chrome()
    profile = os.path.join(os.environ.get("TEMP", "/tmp"), "dsh_p2enc")
    os.makedirs(profile, exist_ok=True)
    port = free_port()
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--first-run",
         "--allow-file-access-from-files", "--window-size=900,700",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = None
        for _ in range(60):
            time.sleep(0.3)
            try:
                ts = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                pages = [t for t in ts if t["type"] == "page"]
                if pages:
                    ws = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:                        # noqa: BLE001
                pass
        if not ws:
            raise RuntimeError("浏览器起不来")
        cdp = CDP(ws)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Page.navigate", url="file:///" + page.replace("\\", "/"))
        time.sleep(1.5)
        spec = json.dumps({"width": width_mm, "height": height_mm, "image": image_data_url})
        cdp.eval(f"__RENDER__({spec})")
        deadline = time.time() + timeout
        out = err = None
        while time.time() < deadline:
            time.sleep(0.4)
            out = cdp.eval("window.__OUT__")
            err = cdp.eval("window.__ERR__")
            if out or err:
                break
        cdp.close()
        if err:
            raise RuntimeError(f"SDK 报错: {err}")
        if not out or not out.get("hex"):
            raise RuntimeError("SDK 没有返回数据")
        return bytes.fromhex(out["hex"])
    finally:
        proc.terminate()
        try:
            os.remove(page)
        except OSError:
            pass


def encode_png(path: str, width_mm: float = 50, height_mm: float = 30) -> bytes:
    """把本地 PNG 编码成打印流（自动缩放到标签尺寸、白底）。"""
    from PIL import Image

    img = Image.open(path).convert("RGB")
    target = (int(width_mm * 8), int(height_mm * 8))
    canvas = Image.new("RGB", target, "white")
    ratio = min(target[0] / img.width, target[1] / img.height)
    resized = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))
    canvas.paste(resized, ((target[0] - resized.width) // 2, (target[1] - resized.height) // 2))
    import io as _io

    buf = _io.BytesIO()
    canvas.save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return encode(data_url, width_mm, height_mm)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python p2_sdk.py 图片.png [宽mm] [高mm]")
        sys.exit(1)
    w = float(sys.argv[2]) if len(sys.argv) > 2 else 50
    h = float(sys.argv[3]) if len(sys.argv) > 3 else 30
    stream = encode_png(sys.argv[1], w, h)
    print(f"  {len(stream)} 字节: {stream[:40].hex(' ')} …")
