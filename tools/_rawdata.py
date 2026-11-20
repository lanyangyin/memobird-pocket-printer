"""用官方 JS SDK 在无头 Chrome 里生成 50x30 标签的**真实打印字节流**。

原理：LPAPI 支持 `jobName = "#!#RawData#!#"`，commitJob() 会返回二进制数据而不是打印。
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = r"C:\Users\18898\PycharmProjects\apk-re-yddyj"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_static_page import CDP, find_chrome, free_port  # noqa: E402

SDK = os.path.join(ROOT, "weida", "docs", "lpapi", "package", "libs", "index.umd.js").replace("\\", "/")
PAGE = os.path.join(ROOT, "weida", "docs", "_rawdata_%d.html" % int(time.time()))

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script src="file:///__SDK__"></script>
<script>
window.__OUT__ = null;
window.__ERR__ = null;
async function run() {
  try {
    const api = LPAPI.LPAPI.create({ webBLE: false, webHID: false, logLevel: 0 });
    api.startJob({ width: 50, height: 30, jobName: "#!#RawData#!#" });
    // 画个明显的图案：外框 + 文字
    // 满页黑块：用 1x1 黑色 canvas 拉伸，最直接
    const c = document.createElement("canvas"); c.width = 400; c.height = 240;
    const g = c.getContext("2d"); g.fillStyle = "#000"; g.fillRect(0, 0, 400, 240);
    api.drawImage && api.drawImage({ image: c, x: 0, y: 0, width: 50, height: 30 });
    const res = await api.commitJob();
    const pd = res && res.resultInfo && res.resultInfo.printData;
    const out = [];
    function walk(x, depth) {
      if (!x || depth > 6) return;
      if (x instanceof Uint8Array || (x.buffer && x.byteLength !== undefined && typeof x.length === "number")) {
        const u = new Uint8Array(x.buffer || x, x.byteOffset || 0, x.byteLength || x.length);
        for (const b of u) out.push(b);
        return;
      }
      if (Array.isArray(x)) { for (const it of x) walk(it, depth + 1); return; }
      if (typeof x === "object") {
        const ks = Object.keys(x).filter((k) => /^\d+$/.test(k)).map(Number).sort((a,b)=>a-b);
        if (ks.length) { for (const k of ks) out.push(x[k] & 0xFF); return; }
        for (const k of Object.keys(x)) walk(x[k], depth + 1);
      }
    }
    walk(pd, 0);
    let buf = out.length ? Uint8Array.from(out) : null;
    if (Array.isArray(pd)) {
      // 可能是 Uint8Array 数组，或 {data:[...]} 对象数组
      const parts = [];
      for (const it of pd) {
        if (it instanceof Uint8Array) parts.push(it);
        else if (it && it.buffer && it.byteLength !== undefined) parts.push(new Uint8Array(it.buffer));
        else if (it && it.data) parts.push(Uint8Array.from(it.data));
        else if (Array.isArray(it)) parts.push(Uint8Array.from(it));
      }
      const total = parts.reduce((a, b) => a + b.length, 0);
      buf = new Uint8Array(total);
      let off = 0;
      for (const p of parts) { buf.set(p, off); off += p.length; }
    }
    const data = buf || pd;
    if (!buf && data instanceof Uint8Array) buf = data;
    else if (typeof data === "string") {
      // 可能是 base64 或二进制串
      try { const bin = atob(data); buf = new Uint8Array(bin.length);
            for (let i=0;i<bin.length;i++) buf[i]=bin.charCodeAt(i); } catch(e) { buf = null; }
    } else if (data && data.buffer) buf = new Uint8Array(data.buffer);
    let hex = "";
    if (buf) { for (let i=0;i<buf.length;i++) hex += buf[i].toString(16).padStart(2,"0"); }
    const ri = res && res.resultInfo;
    let desc = null;
    try {
      const pd0 = Array.isArray(pd) ? pd[0] : pd;
      desc = {
        isArr: Array.isArray(pd), len: pd && pd.length,
        t0: Object.prototype.toString.call(pd0),
        k0: pd0 && typeof pd0 === "object" ? Object.keys(pd0).slice(0, 12) : null,
        s0: pd0 && typeof pd0 === "object" && !(pd0 instanceof Uint8Array)
            ? JSON.stringify(pd0).slice(0, 300) : null,
        isU8: pd0 instanceof Uint8Array,
        blen: pd0 && pd0.byteLength,
      };
    } catch (e) { desc = String(e); }
    window.__OUT__ = { desc: desc, status: res && res.statusCode, type: Object.prototype.toString.call(data),
                       len: buf ? buf.length : -1, hex: hex,
                       keys: ri ? Object.keys(ri) : null,
                       pdType: ri && Object.prototype.toString.call(ri.printData),
                       pdKeys: ri && ri.printData && typeof ri.printData === "object" ? Object.keys(ri.printData) : null,
                       pdLen: ri && ri.printData ? (ri.printData.length || (ri.printData.data && ri.printData.data.length)) : null,
                       sample: typeof data === "string" ? data.slice(0, 80) : null,
                       fullJson: (() => { try { return JSON.stringify(pd); } catch(e) { return null; } })() };
  } catch (e) { window.__ERR__ = String(e && e.stack || e); }
}
</script></body></html>"""


def main():
    html = HTML.replace("__SDK__", SDK)
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(html)

    chrome = find_chrome()
    profile = os.path.join(os.environ.get("TEMP", "/tmp"), "dsh_rawdata")
    os.makedirs(profile, exist_ok=True)
    port = free_port()
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--first-run",
         "--allow-file-access-from-files", "--window-size=800,600",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    for _ in range(50):
        time.sleep(0.3)
        try:
            ts = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
            pages = [t for t in ts if t["type"] == "page"]
            if pages:
                ws = pages[0]["webSocketDebuggerUrl"]
                break
        except Exception:                            # noqa: BLE001
            pass
    if not ws:
        print("  浏览器没起来")
        return 1
    cdp = CDP(ws)
    cdp.call("Page.enable")
    cdp.call("Runtime.enable")
    cdp.call("Page.navigate", url="file:///" + PAGE.replace("\\", "/"))
    time.sleep(2.0)
    cdp.eval("run()")
    for _ in range(20):
        time.sleep(0.5)
        out = cdp.eval("window.__OUT__")
        err = cdp.eval("window.__ERR__")
        if out or err:
            break
    else:
        out, err = None, "超时"

    if err:
        print("  ❌ SDK 报错：", err)
    if out:
        print(f"  status={out['status']} type={out['type']} len={out['len']}")
        print("  desc:", out.get("desc"))
        if out.get("keys"):
            print("  resultInfo keys:", out["keys"])
        if out.get("sample"):
            print("  sample:", out["sample"][:60])
        fj = out.get("fullJson")
        if fj:
            data = json.loads(fj)
            nums = []

            def walk(x):
                if isinstance(x, list):
                    for it in x:
                        walk(it)
                elif isinstance(x, dict):
                    keys = [k for k in x.keys() if k.isdigit()]
                    if keys:
                        for k in sorted(keys, key=int):
                            v = x[k]
                            if isinstance(v, int):
                                nums.append(v & 0xFF)
                    else:
                        for v in x.values():
                            walk(v)
                elif isinstance(x, int):
                    nums.append(x & 0xFF)

            walk(data)
            if nums:
                out["hex"] = bytes(nums).hex()
                out["len"] = len(nums)

        if out.get("hex"):
            hx = out["hex"]
            print(f"  字节流（前 200 字节）:\n    {hx[:400]}")
            with open(os.path.join(ROOT, "weida", "docs", "rawdata_50x30.hex"), "w") as f:
                f.write(hx)
            print(f"  已保存 {len(hx)//2} 字节 → weida/docs/rawdata_50x30.hex")
    cdp.close()
    proc.terminate()
    return 0


sys.exit(main())
