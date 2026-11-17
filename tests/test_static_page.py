#!/usr/bin/env python3
"""
tests/test_static_page.py — 端到端验证「纯静态页」在真浏览器里能编码

做法：起一个 headless Chrome 打开 docs/index.html（file://，没有任何服务端），
      通过 DevTools 协议在页面里调用 encode()（apps/static-web/app.js 的顶层函数），把帧 hex 拿回来，
      和 Python 侧的帧逐字节比对。

    python tests/test_static_page.py                # 找不到浏览器就跳过（exit 0）
    python tests/test_static_page.py --keep         # 保留临时 profile 便于排查

CI 里 ubuntu-latest 自带 Chrome，所以这个测试也能跑。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from memobird_printer import packet  # noqa: E402

PAGE = os.path.join(ROOT, "docs", "index.html")

CHROME_CANDIDATES = [
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

fails: list[str] = []
passes = 0


def check(name: str, got, want) -> None:
    global passes
    if got == want:
        passes += 1
        print(f"  [OK ] {name}")
    else:
        fails.append(name)
        print(f"  [FAIL] {name}")
        print(f"         got  {str(got)[:160]}")
        print(f"         want {str(want)[:160]}")


def find_chrome() -> str | None:
    for p in CHROME_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    for name in ("google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def http_json(url: str, timeout: float = 5):
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


class CDP:
    def __init__(self, ws_url: str):
        import websocket

        self.ws = websocket.create_connection(ws_url, timeout=20)
        self.seq = 0

    def call(self, method: str, **params):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.seq:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def eval(self, expr: str, await_promise: bool = True):
        res = self.call("Runtime.evaluate", expression=expr, awaitPromise=await_promise,
                        returnByValue=True, timeout=20000)
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"].get("text") or str(res["exceptionDetails"]))
        return res.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def main() -> int:
    keep = "--keep" in sys.argv
    chrome = find_chrome()
    if not chrome:
        print("没找到 Chrome/Chromium —— 跳过（不影响其它测试）")
        return 0
    if not os.path.isfile(PAGE):
        print(f"缺少 {PAGE} —— 先跑 python apps/static-web/build.py")
        return 1

    print(f"浏览器: {chrome}")
    port = free_port()
    profile = tempfile.mkdtemp(prefix="mb_chrome_")
    url = "file:///" + PAGE.replace("\\", "/")
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--no-first-run", "--no-default-browser-check",
         "--disable-features=Translate", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    cdp = None
    try:
        ws_url = None
        for _ in range(60):
            time.sleep(0.5)
            try:
                targets = http_json(f"http://127.0.0.1:{port}/json/list")
            except Exception:
                continue
            for t in targets:
                if t.get("type") == "page" and "index.html" in t.get("url", ""):
                    ws_url = t.get("webSocketDebuggerUrl")
                    break
            if ws_url:
                break
        if not ws_url:
            print("拿不到 DevTools 目标 —— 跳过")
            return 0

        cdp = CDP(ws_url)
        cdp.call("Runtime.enable")

        # 等页面初始化完成（client 模式会写入 #mode）
        mode_text = None
        for _ in range(40):
            mode_text = cdp.eval("(document.querySelector('#mode')||{}).textContent", await_promise=False)
            if mode_text and "检测" not in mode_text:
                break
            time.sleep(0.25)
        print(f"\n1) 页面启动")
        check("编码模式 = 浏览器本地", "浏览器本地编码" in (mode_text or ""), True)
        check("MBEncoder 已加载", cdp.eval("typeof MBEncoder", await_promise=False), "object")
        check("MBRender 已加载", cdp.eval("typeof MBRender", await_promise=False), "object")
        check("MBBle 已加载", cdp.eval("typeof MBBle", await_promise=False), "object")
        check("MB_STANDALONE 标志", cdp.eval("window.MB_STANDALONE === true", await_promise=False), True)

        # 1b) BLE 选特征值：回归"Chrome 新版没有同步 characteristics 属性"
        print("\n1b) BLE 选特征值（模拟 GT1，只实现 getCharacteristics）")
        js_ble = """(async () => {
          const mk = (uuid, props) => ({ uuid, properties: props });
          const services = [{ uuid: '0000ff00-0000-1000-8000-00805f9b34fb',
            getCharacteristics: async () => [
              mk('0000ff02-0000-1000-8000-00805f9b34fb', { write: true, writeWithoutResponse: true }),
              mk('0000ff01-0000-1000-8000-00805f9b34fb', { notify: true }),
            ] }];
          const r = await MBBle.pickWrite(services);
          return JSON.stringify({
            write: r.write && r.write.uuid,
            notify: r.notify && r.notify.uuid,
            count: r.all.length,
          });
        })()"""
        got_ble = json.loads(cdp.eval(js_ble))
        check("挑到 ff02", got_ble["write"], "0000ff02-0000-1000-8000-00805f9b34fb")
        check("挑到 ff01", got_ble["notify"], "0000ff01-0000-1000-8000-00805f9b34fb")
        check("特征值计数", got_ble["count"], 2)

        # 2) ASCII 文字走 GBK 帧：与 Python 逐字节比对
        #    中文不走这条路 —— 这台固件的 GBK 文本帧没有中文字形，会打成黑块，
        #    所以代码把非 ASCII 强制改走位图（见第 3 项）。
        print("\n2) 浏览器内编码（ASCII → GBK 帧）")
        js = """(async () => {
          const j = await encode({kind:'text', text:'Hello', format:'gbk'});
          return JSON.stringify({
            hex: Array.from(j.frames[0], b => b.toString(16).padStart(2,'0')).join(''),
            chunks: j.meta.chunks, bytes: j.meta.bytes, format: j.meta.format,
          });
        })()"""
        got = json.loads(cdp.eval(js))
        want_frame = packet.job_for_text("Hello", encoding="gbk").frames[0].hex()
        check("帧 hex 与 Python 一致", got["hex"], want_frame)
        check("meta.format", got["format"], "gbk")

        # 2b) 中文必须走位图
        print("\n2b) 中文自动改走位图（GBK 文本帧无中文字形）")
        js_cn = """(async () => {
          const j = await encode({kind:'text', text:'中文测试', format:'gbk', feedLines:3});
          return JSON.stringify({format: j.meta.format, chunks: j.meta.chunks});
        })()"""
        cn = json.loads(cdp.eval(js_cn))
        check("中文 → format=bmp", cn["format"], "bmp")
        check("中文 → 有内容帧", cn["chunks"] > 0, True)

        # 3) 文字转位图（不依赖 GBK 的路径）
        print("\n3) 浏览器内编码（文字 → 位图 → BMP 任务）")
        js2 = """(async () => {
          const j = await encode({kind:'text', text:'Ab', format:'bmp', mode:'threshold'});
          return JSON.stringify({
            chunks: j.meta.chunks, bytes: j.meta.bytes, w: j.meta.width, h: j.meta.height,
            head: Array.from(j.frames[0].slice(0,3), b => b.toString(16).padStart(2,'0')).join(''),
            len: j.frames[0].length,
          });
        })()"""
        got2 = json.loads(cdp.eval(js2))
        check("宽度 384", got2["w"], 384)
        check("帧头 AA", got2["head"][:2], "aa")
        check("命令字 0x04(打印)", got2["head"][4:6], "04")
        check("有载荷", got2["bytes"] > 100, True)
        check("高度合理", 30 <= got2["h"] <= 120, True)

        # 4) 校准图（canvas 绘制 + 抖动）
        print("\n4) 校准图（canvas → 抖动 → BMP）")
        js3 = """(() => {
          const g = MBRender.calibrationGray();
          const d = MBEncoder.ditherToRaw(g.gray, g.w, g.h, 'threshold', 128);
          return JSON.stringify({w: d.w, h: d.h, bytes: d.raw.length, black: d.raw.reduce((a,b)=>a+((b*8)%9),0)});
        })()"""
        got3 = json.loads(cdp.eval(js3, await_promise=False))
        check("校准图 384 宽", got3["w"], 384)
        check("校准图高度 320", got3["h"], 320)
        check("裸位图字节 = 48*320", got3["bytes"], 48 * 320)

        # 5) GBK 码表在浏览器里可用
        print("\n5) 浏览器内 GBK 码表")
        js4 = """(() => {
          const hex = s => Array.from(GBK.encode(s), b => b.toString(16).padStart(2,'0')).join('');
          return JSON.stringify({ni: hex('你好'), emoji: GBK.encode('hi 😀'), valid: GBK.valid});
        })()"""
        got4 = json.loads(cdp.eval(js4, await_promise=False))
        check("你好 → c4e3bac3", got4["ni"], "c4e3bac3")
        check("emoji 不可编码 → null", got4["emoji"], None)
        check("码位数 21791", got4["valid"], 21791)

    finally:
        if cdp:
            cdp.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if not keep:
            shutil.rmtree(profile, ignore_errors=True)

    print()
    if fails:
        print(f"失败 {len(fails)} 项: {fails}")
        return 1
    print(f"全部通过 ✅（{passes} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
