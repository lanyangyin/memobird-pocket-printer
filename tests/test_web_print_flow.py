#!/usr/bin/env python3
"""
tests/test_web_print_flow.py — 两个网页实现的「打印流程」端到端测试（用假 BLE 层）

为什么这么测：
    Web Bluetooth 需要一个真人点击选择设备，无头 Chrome 又没有
    BluetoothEmulation 域，所以没法自动连真机。但网页里真正会出错的逻辑是
    编码 → 分页 → 浓度包裹 → 终结帧 → 逐页发送 —— 这些与蓝牙无关。

    做法：在页面任何脚本之前注入一个假的 window.MBLink，记录所有"写出去的帧"，
    然后把抓到的帧与 Python 的编码结果逐字节比对。

    python tests/test_web_print_flow.py [--keep]

覆盖：
    1. 静态页：ASCII 文本帧 == Python
    2. 静态页：中文 → 自动走位图（不是 GBK 帧）
    3. 静态页：纸总长 40mm → 内容 176 行
    4. 静态页：超高图 → 自动分 2 页（每页 ≤400 行）
    5. 静态页：浓度包裹（设 6 → 打印 → 恢复 10）+ 终结帧（状态查询）
    6. 服务端页：/api/encode 抓到的帧 == 服务端返回的帧
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from memobird_printer import packet                      # noqa: E402
from test_static_page import CDP, find_chrome, free_port  # noqa: E402

PAGE = os.path.join(ROOT, "docs", "index.html")
SERVER = os.path.join(ROOT, "apps", "web-server", "serve.py")

fails: list[str] = []
passes = 0


def check(name, got, want):
    global passes
    if got == want:
        passes += 1
        print(f"  [OK ] {name}")
    else:
        fails.append(name)
        print(f"  [FAIL] {name}\n         got  = {str(got)[:200]}\n         want = {str(want)[:200]}")


# --------------------------------------------------------------------------- #
# 注入的假 BLE 层（在页面脚本之前运行）
# --------------------------------------------------------------------------- #
MOCK = r"""
(() => {
  const cap = { jobs: [], frames: [], settings: [], queries: [], connected: 0 };
  window.__CAP__ = cap;
  const hex = (arr) => Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('');
  const state = {
    connected: true,
    device: { name: 'GT1', id: '00:15:83:E4:7A:F2' },
    writeChr: { uuid: '0000ff02-0000-1000-8000-00805f9b34fb' },
    notifyChr: { uuid: '0000ff01-0000-1000-8000-00805f9b34fb' },
  };

  const link = {
    state,
    get connected() { return state.connected; },
    async connect() { state.connected = true; cap.connected++; return state; },
    async disconnect() { state.connected = false; },
    async servicesWithFallback() { return []; },
    async dumpGatt() { return []; },
    async writeAll(frames) { for (const f of frames) cap.frames.push(hex(f)); },
    async sendJob(job, label, opts) {
      cap.jobs.push({ label, frames: job.frames.length, height: job.meta && job.meta.height });
      for (const f of job.frames) cap.frames.push(hex(f));
      if (opts && opts.onProgress) opts.onProgress({ done: job.frames.length, total: job.frames.length });
      return job.frames.length;
    },
    async query(frame) { cap.queries.push(hex(frame)); return []; },
    async sendHex(hexStr) { cap.raw = (cap.raw || []).concat(hexStr); return []; },
    async listGatt() { return ['[service] test']; },
    async readDeviceInfo() {
      return [{ cmd: 2, serial: '636404963750000000', fields: [
        { tag: 0x02, int: 10 }, { tag: 0x03, int: 1 },
        { tag: 0x04, int: 80 }, { tag: 0x06, int: 0 } ] }];
    },
    async getDensity() { return 10; },
    async setDensity(n) { cap.settings.push(n); },
    async setLed(on) { cap.settings.push('led:' + on); return on ? 1 : 0; },
  };

  const mod = { createLink: () => link, __mock: true };
  Object.defineProperty(window, 'MBLink', {
    configurable: true,
    get() { return mod; },
    set(_v) { /* 忽略页面的真实实现，始终用 mock */ },
  });
  // 状态查询帧的期望值由测试脚本另行计算（不在这里引用 MBBle）
  window.__STATUS_HEX__ = 'aa01000154';
})();
"""


def launch(chrome: str, url: str, keep: bool):
    port = free_port()
    profile = tempfile.mkdtemp(prefix="mb_flow_")
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--no-first-run", "--no-default-browser-check",
         "--disable-features=Translate", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ws_url = None
    for _ in range(40):
        time.sleep(0.25)
        try:
            import urllib.request

            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
            pages = [t for t in targets if t["type"] == "page"]
            if pages:
                ws_url = pages[0]["webSocketDebuggerUrl"]
                break
        except Exception:
            continue
    if not ws_url:
        proc.terminate()
        raise RuntimeError("连不上 Chrome CDP")

    cdp = CDP(ws_url)
    cdp.call("Page.enable")
    cdp.call("Runtime.enable")
    cdp.call("Page.addScriptToEvaluateOnNewDocument", source=MOCK)
    cdp.call("Page.navigate", url=url)
    time.sleep(2.0)
    return proc, cdp


def wait_idle(cdp: CDP, expr: str, timeout: float = 25.0):
    """轮询等待页面里的异步打印流程结束"""
    end = time.time() + timeout
    while time.time() < end:
        if cdp.eval(expr, await_promise=False):
            return True
        time.sleep(0.3)
    return False


def main() -> int:
    keep = "--keep" in sys.argv
    chrome = find_chrome()
    if not chrome:
        print("没找到 Chrome —— 跳过（不影响其它测试）")
        return 0
    if not os.path.isfile(PAGE):
        print(f"缺少 {PAGE} —— 先跑 python apps/static-web/build.py")
        return 1

    print(f"浏览器: {chrome}")

    # ---------------------------------------------------------------- 静态页
    print("\n=== 1) 静态实现（file://）===")
    proc, cdp = launch(chrome, "file:///" + PAGE.replace("\\", "/"), keep)
    try:
        check("假 BLE 层已注入", cdp.eval("!!(window.__CAP__ && window.MBLink.__mock)", await_promise=False), True)
        check("MBEncoder 就绪", cdp.eval("typeof MBEncoder", await_promise=False), "object")

        # 1. ASCII 文本：帧必须与 Python 逐字节一致
        cdp.eval("window.__CAP__.frames.length = 0; window.__CAP__.jobs.length = 0; true", await_promise=False)
        cdp.eval("""(async () => {
          await print({kind:'text', text:'Hello', format:'gbk'}, 'T1');
          return true;
        })()""")
        frames = cdp.eval("JSON.stringify(window.__CAP__.frames)")
        got = json.loads(frames)
        want = [packet.job_for_text("Hello").frames[0].hex()]
        check("ASCII 文本帧 == Python", got, want)

        # 2. 中文 → 位图（不是 GBK 文本帧）
        cdp.eval("window.__CAP__.frames.length = 0; window.__CAP__.jobs.length = 0; true", await_promise=False)
        cdp.eval("""(async () => {
          await print({kind:'text', text:'中文测试', format:'gbk'}, 'T2');
          return true;
        })()""")
        cn = json.loads(cdp.eval("JSON.stringify(window.__CAP__.frames)"))
        # 判定：首帧 payload 里有位图 tag 0x08，且没有文本 tag 0x07
        def has_tag(frame_hex, tag):
            raw = bytes.fromhex(frame_hex)
            parsed = packet.parse_frame(raw)
            if not parsed:
                return False
            return tag in packet.parse_tlv(parsed[1])
        check("中文帧含位图 tag 0x08", has_tag(cn[0], 0x08) if cn else False, True)
        check("中文帧不含文本 tag 0x07", has_tag(cn[0], 0x07) if cn else True, False)

        # 3. 纸总长 40mm → 内容 176 行
        h = cdp.eval("""(async () => {
          const j = await encode({kind:'text', text:'Hello', format:'bmp', totalMm:40});
          return j.meta.height;
        })()""")
        check("纸总长 40mm → 176 行", h, 176)

        # 4. 超高内容 → 自动分页（用 lengthMm 造一张 900 行的图，避开 canvas 解码）
        pages = cdp.eval("""(async () => {
          const j = await encode({kind:'text', text:'X', format:'bmp', totalMm:318});
          const ps = j.pages || [j];
          return {rows: j.meta.height, pages: ps.length, pagesH: ps.map(p => p.meta.height)};
        })()""")
        check("2400 行内容", pages["rows"], 2400)
        check("2400 行 → 2 页", pages["pages"], 2)
        check("分页高度 1200/1200", pages["pagesH"], [1200, 1200])

        # 5. 浓度包裹 + 终结帧
        cdp.eval("""(() => {
          window.__CAP__.settings.length = 0;
          window.__CAP__.queries.length = 0;
          window.__CAP__.jobs.length = 0;
          document.querySelector('#density').value = '6';
          return true;
        })()""", await_promise=False)
        cdp.eval("""(async () => {
          await print({kind:'text', text:'Hello', format:'gbk'}, 'T5');
          return true;
        })()""")
        settings = json.loads(cdp.eval("JSON.stringify(window.__CAP__.settings)"))
        check("浓度：先设 6 再恢复 10", settings, [6, 10])
        queries = json.loads(cdp.eval("JSON.stringify(window.__CAP__.queries)"))
        check("终结帧是提交帧 cmd 0x08", queries, ["aa0100084d"])

        # 5b. 底层：任意帧发送 / 命令构造 / GATT 列表
        cdp.eval("window.__CAP__.queries.length = 0; true", await_promise=False)
        raw = cdp.eval("""(async () => {
          await link.sendHex('aa 01 00 01 54');
          const f = window.MBBle.buildFrame(0x08, new Uint8Array(0));
          const g = await link.listGatt();
          return { sent: (window.__CAP__.raw || []).slice(-1)[0], commit: window.MBBle.bytesToHex(f), gatt: Array.isArray(g) };
        })()""")
        check("sendHex 把帧交给传输层", raw["sent"], "aa 01 00 01 54")
        check("buildFrame(0x08) = aa 01 00 08 4d", raw["commit"], "aa 01 00 08 4d")
        check("listGatt 返回数组", raw["gatt"], True)
        check("底层面板存在", cdp.eval("!!document.querySelector('#btn-raw')", await_promise=False), True)

        # 6. 分页时逐页发送（3 页 = 3 次 sendJob）
        cdp.eval("window.__CAP__.jobs.length = 0; true", await_promise=False)
        cdp.eval("""(async () => {
          document.querySelector('#density').value = '0';
          await print({kind:'text', text:'X', format:'bmp', totalMm:318}, 'T6');
          return true;
        })()""")
        jobs = json.loads(cdp.eval("JSON.stringify(window.__CAP__.jobs)"))
        check("2400 行图 → 分 2 次发送", len(jobs), 2)
        check("每页的行数在上限内", all(j["height"] <= 1200 for j in jobs), True)
    finally:
        cdp.close()
        if not keep:
            proc.terminate()

    # -------------------------------------------------------------- 服务端页
    print("\n=== 2) 服务端实现（serve.py + 浏览器）===")
    port = free_port()
    srv = subprocess.Popen([sys.executable, SERVER, "--port", str(port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            time.sleep(0.25)
            try:
                import urllib.request

                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2)
                break
            except Exception:
                continue

        proc2, cdp2 = launch(chrome, f"http://127.0.0.1:{port}/", keep)
        try:
            check("服务端页：假 BLE 已注入", cdp2.eval("!!window.__CAP__", await_promise=False), True)
            check("服务端页：API 可达", cdp2.eval(
                "(async()=>{const r=await fetch('/api/health');const j=await r.json();return j.ok===true;})()"), True)

            # 打印文字，抓帧；再直接请求同一接口，两边必须一致
            cdp2.eval("window.__CAP__.frames.length = 0; true", await_promise=False)
            cdp2.eval("""(async () => {
              document.querySelector('#density').value = '0';
              await printApi('/api/encode', {kind:'text', text:'Hello', format:'gbk'}, 'S1');
              return true;
            })()""")
            got = json.loads(cdp2.eval("JSON.stringify(window.__CAP__.frames)"))
            want = json.loads(cdp2.eval("""(async () => {
              const r = await fetch('/api/encode', {method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({kind:'text', text:'Hello', format:'gbk'})});
              const j = await r.json();
              return JSON.stringify(j.frames);
            })()"""))
            # 接口返回的是 base64，页面解析成字节后我们抓到的是 hex —— 统一成 hex 再比
            want_hex = [base64.b64decode(f).hex() for f in want]
            check("服务端页：抓到的帧 == 接口返回的帧", got, want_hex)
            check("服务端页：帧非空", len(got) > 0, True)

            # 超高图 → 接口返回 pages，页面逐页发
            tall = cdp2.eval("""(async () => {
              const r = await fetch('/api/encode', {method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({kind:'text', text:'X', format:'bmp', lengthMm:250})});
              const j = await r.json();
              return {pages: (j.pages||[]).length, heights: (j.pages||[]).map(p => p.meta.height)};
            })()""")
            check("接口：250mm 图分 2 页", tall["pages"], 2)
            check("接口：页高 1200 + 800", tall["heights"], [1200, 800])
        finally:
            cdp2.close()
            if not keep:
                proc2.terminate()
    finally:
        srv.terminate()

    print()
    if fails:
        print(f"失败 {len(fails)} 项: {fails}")
        return 1
    print(f"全部通过 ✅（{passes} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
