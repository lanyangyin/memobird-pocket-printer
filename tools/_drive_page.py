"""真开浏览器窗口，用 CDP 的真实鼠标/键盘事件驱动页面（不是 element.click()）。

用法：
    python tools/_drive_page.py open        # 启动真实 Chrome 窗口，打开服务端页面
    python tools/_drive_page.py click "选择器"   # 在元素中心真实点击一下
    python tools/_drive_page.py type "文本"      # 真实键盘输入到当前焦点
    python tools/_drive_page.py shot 文件名      # 截图
    python tools/_drive_page.py eval "js"        # 取一个值（只读检查用）
    python tools/_drive_page.py logs             # 打印页面日志区内容
    python tools/_drive_page.py quit             # 关闭窗口

Chrome 会一直留着（--user-data-dir 固定），后续命令复用同一个窗口。
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 9223
PROFILE = os.path.join(os.environ.get("TEMP", "/tmp"), "dsh_drive_profile")
URL = "http://127.0.0.1:8766/"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome():
    for c in CHROME_CANDIDATES:
        if c and os.path.exists(c):
            return c
    raise SystemExit("找不到 chrome.exe")


def ws_url():
    for _ in range(60):
        try:
            ts = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2))
            pages = [t for t in ts if t["type"] == "page" and t.get("url", "").startswith("http")]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.25)
    return None


class CDP:
    def __init__(self, url):
        from websocket import create_connection

        self.ws = create_connection(url, timeout=60)
        self.mid = 0

    def call(self, method, **params):
        self.mid += 1
        self.ws.send(json.dumps({"id": self.mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def eval(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("text") or "eval 出错")
        return r["result"].get("value")


def connect():
    url = ws_url()
    if not url:
        raise SystemExit("浏览器没开，先运行： python tools/_drive_page.py open")
    return CDP(url)


def center_of(cdp, selector):
    box = cdp.eval(
        "(() => { const el = document.querySelector(%r);"
        " if (!el) return null;"
        " el.scrollIntoView({block:'center'});"
        " const r = el.getBoundingClientRect();"
        " return {x: r.left + r.width/2, y: r.top + r.height/2,"
        "         w: r.width, h: r.height, text: (el.textContent||'').trim().slice(0,20)}; })()"
        % selector
    )
    if not box:
        raise SystemExit(f"找不到元素：{selector}")
    return box


def real_click(cdp, selector):
    box = center_of(cdp, selector)
    x, y = box["x"], box["y"]
    cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, buttons=0)
    cdp.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y,
             button="left", buttons=1, clickCount=1)
    cdp.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y,
             button="left", buttons=0, clickCount=1)
    return box


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "open"

    if cmd == "open":
        chrome = find_chrome()
        if ws_url():
            print("浏览器已经在运行，直接复用")
            return
        os.makedirs(PROFILE, exist_ok=True)
        subprocess.Popen(
            [chrome, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
             "--no-first-run", "--no-default-browser-check",
             "--window-size=1280,1000", URL],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        url = ws_url()
        print("已启动真实 Chrome：" + (url or "（还没连上）"))
        return

    cdp = connect()

    if cmd == "click":
        box = real_click(cdp, sys.argv[2])
        print(f"已在 ({box['x']:.0f},{box['y']:.0f}) 真实点击「{box['text']}」")
    elif cmd == "type":
        cdp.call("Input.insertText", text=sys.argv[2])
        print(f"已输入：{sys.argv[2]}")
    elif cmd == "shot":
        out = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
        res = cdp.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
        with open(out, "wb") as f:
            f.write(base64.b64decode(res["data"]))
        print("截图：" + out)
    elif cmd == "eval":
        print(json.dumps(cdp.eval(sys.argv[2]), ensure_ascii=False, indent=1))
    elif cmd == "logs":
        text = cdp.eval("document.querySelector('#log').textContent")
        print(text)
    elif cmd == "quit":
        cdp.call("Browser.close")
        print("已关闭浏览器")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
