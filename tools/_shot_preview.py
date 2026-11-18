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
         deviceScaleFactor=1, mobile=False)
cdp.call("Page.navigate", url="file:///" + PAGE.replace("\\", "/"))
time.sleep(2.0)

JS = """
(async () => {
  const c = document.createElement('canvas');
  c.width = 200; c.height = 300;
  const g = c.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, 200, 300);
  g.fillStyle = '#000';
  for (let i = 0; i < 6; i++) g.fillRect(10, 20 + i * 45, 180, 20);
  const url = c.toDataURL();
  await preview({kind: 'image', dataUrl: url, format: 'bmp', mode: 'threshold'});
  return true;
})()
"""
cdp.eval(JS)
time.sleep(0.6)

BOX = """
(() => {
  const w = document.querySelector('.preview-wrap');
  const r = w.getBoundingClientRect();
  const img = document.querySelector('#preview');
  const ir = img.getBoundingClientRect();
  return {wrapW: Math.round(r.width), wrapH: Math.round(r.height),
          imgW: Math.round(ir.width), imgH: Math.round(ir.height),
          left: Math.round(r.left), top: Math.round(r.top + window.scrollY),
          note: (document.querySelector('#preview-note') || {}).textContent || ''};
})()
"""
box = cdp.eval(BOX)
print("  wrap", box["wrapW"], "x", box["wrapH"], " img", box["imgW"], "x", box["imgH"])
print("  说明文字:", box["note"][:40])

res = cdp.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
out = os.path.join(ROOT, "preview_shot.png")
open(out, "wb").write(base64.b64decode(res["data"]))
print("  截图:", out, os.path.getsize(out), "bytes")
cdp.close()
proc.terminate()
