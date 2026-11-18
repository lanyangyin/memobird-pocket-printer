"""检查宽/窄两种视口下的布局：预览是否拉伸、状态条宽度、是否横向溢出。"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = r"C:\Users\18898\PycharmProjects\apk-re-yddyj"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_static_page import CDP, find_chrome, free_port  # noqa: E402

PAGE = os.path.join(ROOT, "docs", "index.html")


def run(width, height, tag):
    chrome = find_chrome()
    port = free_port()
    prof = tempfile.mkdtemp(prefix="shot_")
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
         f"--window-size={width},{height}", f"--remote-debugging-port={port}",
         f"--user-data-dir={prof}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ws = None
    for _ in range(40):
        time.sleep(0.25)
        try:
            ts = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
            pg = [t for t in ts if t["type"] == "page"]
            if pg:
                ws = pg[0]["webSocketDebuggerUrl"]
                break
        except Exception:
            pass
    cdp = CDP(ws)
    cdp.call("Page.enable")
    cdp.call("Runtime.enable")
    cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
             deviceScaleFactor=1, mobile=width < 600)
    cdp.call("Page.navigate", url="file:///" + PAGE.replace("\\", "/"))
    time.sleep(1.8)

    # 一张 300x600 的竖图（非 4:3，方便看出拉伸）
    cdp.eval("""
    (async () => {
      const c = document.createElement('canvas');
      c.width = 300; c.height = 600;
      const g = c.getContext('2d');
      g.fillStyle = '#fff'; g.fillRect(0, 0, 300, 600);
      g.fillStyle = '#000'; g.fillRect(0, 0, 300, 80);
      g.beginPath(); g.arc(60, 400, 50, 0, Math.PI * 2); g.fill();
      for (let i = 0; i < 5; i++) { g.fillRect(120, 100 + i * 60, 160, 30); }
      const url = c.toDataURL();
      await preview({kind: 'image', dataUrl: url, format: 'bmp', mode: 'threshold'});
      return true;
    })()
    """)
    time.sleep(0.5)
    info = cdp.eval("""(() => {
      const de = document.documentElement;
      const img = document.querySelector('#preview');
      const ir = img.getBoundingClientRect();
      const conn = document.querySelector('#conn');
      const cr = conn.getBoundingClientRect();
      const main = document.querySelector('main').getBoundingClientRect();
      return {
        overflowX: de.scrollWidth > de.clientWidth,
        docW: de.scrollWidth,
        imgW: Math.round(ir.width), imgH: Math.round(ir.height),
        naturalW: img.naturalWidth, naturalH: img.naturalHeight,
        connW: Math.round(cr.width), mainW: Math.round(main.width),
      };
    })()""")
    ratio_disp = info["imgW"] / info["imgH"] if info["imgH"] else 0
    ratio_nat = info["naturalW"] / info["naturalH"] if info["naturalH"] else 0
    stretched = abs(ratio_disp - ratio_nat) > 0.02 * ratio_nat
    print(f"  [{tag}] 视口 {width}px  溢出={info['overflowX']}")
    print(f"        预览显示 {info['imgW']}x{info['imgH']}  自然 {info['naturalW']}x{info['naturalH']}"
          f"  比例 {ratio_disp:.3f} vs {ratio_nat:.3f}  拉伸={stretched}")
    print(f"        状态条宽 {info['connW']}px（main {info['mainW']}px）")
    res = cdp.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
    out = os.path.join(ROOT, f"ui_{tag}.png")
    open(out, "wb").write(base64.b64decode(res["data"]))
    cdp.close()
    proc.terminate()
    return stretched, info


if __name__ == "__main__":
    run(1280, 1000, "wide")
    run(390, 900, "narrow")
