"""
memobird/cloud.py — 咕咕机开放平台云端后端

接口（官方《WebAPI》PDF v0.5，open.memobird.cn；无 sign，只有 ak + timestamp）：

    /home/setuserbind            ak, timestamp, memobirdID, useridentifying  → showapi_userid
    /home/printpaper             ak, timestamp, printcontent, memobirdID, userID
    /home/getprintstatus         ak, timestamp, printcontentid               → printflag
    /home/getSignalBase64Pic     ak, imgBase64String                         → 1bpp BMP (base64)
    /home/printpaperFromUrl      ak, timestamp, printUrl, memobirdID, userID
    /home/printpaperFromHtml     ak, timestamp, printHtml, memobirdID, userID

printcontent 形如 `T:<base64(GBK 文本)>` 或 `P:<base64(1bpp BMP)>`，多条用 `|` 连接。
timestamp 形如 `2014-11-14 14:22:39`（空格要 URL 编码）。
"""
from __future__ import annotations

import base64
import time
import urllib.parse
import urllib.request
import json

BASE = "https://open.memobird.cn"


def _ts(when: float | None = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))


class CloudPrinter:
    backend = "cloud"

    def __init__(self, ak: str, memobird_id: str, user_id: int | None = None, *, base: str = BASE, timeout: float = 20):
        self.ak = ak
        self.memobird_id = memobird_id
        self.user_id = user_id
        self.base = base.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: dict) -> dict:
        qs = urllib.parse.urlencode(params)
        url = f"{self.base}{path}?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "memobird-printer/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}

    # ------------------------------------------------------------------ #
    def bind(self, user_identifying: str) -> dict:
        """把设备绑定到自己的账号标识，返回里的 showapi_userid 就是后续的 userID。"""
        r = self._get("/home/setuserbind", {
            "ak": self.ak,
            "timestamp": _ts(),
            "memobirdID": self.memobird_id,
            "useridentifying": user_identifying,
        })
        if isinstance(r, dict) and r.get("showapi_userid"):
            self.user_id = int(r["showapi_userid"])
        return r

    # ------------------------------------------------------------------ #
    def print_content(self, print_content: str) -> dict:
        if self.user_id is None:
            raise RuntimeError("还没有 userID：先调用 bind()（或用 setuserbind 接口拿到 showapi_userid）")
        return self._get("/home/printpaper", {
            "ak": self.ak,
            "timestamp": _ts(),
            "printcontent": print_content,
            "memobirdID": self.memobird_id,
            "userID": self.user_id,
        })

    def print_text(self, text: str, *, encoding: str = "gbk") -> dict:
        if not text.endswith("\n"):
            text += "\n"
        return self.print_content("T:" + base64.b64encode(text.encode(encoding, "replace")).decode())

    def print_bmp(self, bmp: bytes) -> dict:
        return self.print_content("P:" + base64.b64encode(bmp).decode())

    def print_parts(self, *parts: str) -> dict:
        """多条混排：T:...|P:...|T:..."""
        return self.print_content("|".join(parts))

    # ------------------------------------------------------------------ #
    def status(self, print_content_id: str) -> dict:
        return self._get("/home/getprintstatus", {
            "ak": self.ak,
            "timestamp": _ts(),
            "printcontentid": print_content_id,
        })

    def wait_printed(self, print_content_id: str, *, timeout: float = 60, interval: float = 3) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.status(print_content_id)
            if str(r.get("printflag")) == "1":
                return True
            time.sleep(interval)
        return False
