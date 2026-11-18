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
chrome = find_chrome()
port = free_port()
prof = tempfile.mkdtemp(prefix="shot_")
proc = subprocess.Popen(
    [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
     "--window-size=390,900", f"--remote-debugging-port={port}",
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
cdp.call("Emulation.setDeviceMetricsOverride", width=390, height=900,
         deviceScaleFactor=1, mobile=True)
cdp.call("Page.navigate", url="file:///" + PAGE.replace("\\", "/"))
time.sleep(2.0)

# 用一张整宽的测试图（384 宽）
JS = """
(async () => {
  const c = document.createElement('canvas');
  c.width = 384; c.height = 320;
  const g = c.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, 384, 320);
  g.fillStyle = '#000';
  for (let i = 0; i < 5; i++) g.fillRect(i * 8, 20 + i * 55, 384 - i * 16, 22);
  g.font = '20px sans-serif';
  g.fillText('PREVIEW 384', 20, 300);
  state.imageEl = null;
  state.imageDataUrl = c.toDataURL();
  await preview({kind: 'image', dataUrl: c.toDataURL(), format: 'bmp', mode: 'threshold'});
  return true;
})()
"""
cdp.eval(JS)
time.sleep(0.5)

for tab, name in ((0, "text"), (1, "image"), (2, "debug")):
    cdp.eval(f"document.querySelectorAll('.tab')[{tab}].click(); true", await_promise=False)
    time.sleep(0.4)
    res = cdp.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
    out = os.path.join(ROOT, f"ui_mobile_{name}.png")
    open(out, "wb").write(base64.b64decode(res["data"]))
    info = cdp.eval("""(() => {
      const de = document.documentElement;
      return {scrollW: de.scrollWidth, clientW: de.clientWidth};
    })()""")
    print(f"  {name}: 截图 {os.path.getsize(out)//1024}KB  横向溢出={info['scrollW'] > info['clientW']}")

cdp.close()
proc.terminate()
