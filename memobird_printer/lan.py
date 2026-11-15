"""
memobird/lan.py — 局域网直连后端（无 ak、无绑定、无 root）

咕咕机 WiFi 机型在**同网段**时暴露一个 HTTP 服务：

    GET  http://<ip>/sys/printer                  → 状态 JSON
    POST http://<ip>/sys/printer  (JSON body)     → 下发打印
    POST http://<ip>/sys/printer  {command:4,...} → 取消/查询（部分固件）

注意（来自实测记录）：
  * `printID` 每单必须是新值，重复会被**静默丢弃**；
  * 单次 body 超过约 26KB 会被拒（HTTP 500），需要同一 printID 拆 pkgNo/pkgCount；
  * 图片走 printType=5，basetext 是 **1bpp、384 宽、垂直翻转** 的 BMP；
  * 文本走 printType=1，basetext 是 **GBK** 文本的 base64（末尾记得带 \\n）；
  * 该接口非官方公开，固件版本可能改变行为。
"""
from __future__ import annotations

import base64
import json
import socket
import time
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 8
MAX_BODY = 26 * 1024


def _new_print_id() -> int:
    return int(time.time() * 1000) % 2_000_000_000 or 1


class LanPrinter:
    backend = "lan"

    def __init__(self, host: str, *, port: int = 80, timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.base = f"http://{host}" + (f":{port}" if port != 80 else "")
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    def _request(self, data: dict | None = None, method: str = "GET") -> dict:
        url = f"{self.base}/sys/printer"
        body = None
        headers = {"Accept": "application/json"}
        if data is not None:
            body = json.dumps(data, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return {"raw": raw.decode("utf-8", "replace")}

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        return self._request()

    def print_text(self, text: str, *, font_size: int = 1, bold: int = 0, underline: int = 0) -> dict:
        if not text.endswith("\n"):
            text += "\n"
        item = {
            "encodeType": 0,
            "printType": 1,
            "basetext": base64.b64encode(text.encode("gbk", "replace")).decode(),
            "fontSize": font_size,
            "bold": bold,
            "underline": underline,
        }
        return self._send([item])

    def print_image(self, bmp: bytes) -> dict:
        """bmp 需为 384 宽 1bpp、top-down 的 BMP 字节流（见 image.raw_to_bmp）。"""
        item = {"encodeType": 0, "printType": 5, "basetext": base64.b64encode(bmp).decode()}
        return self._send([item])

    def print_raw_image(self, width: int, height: int, raw: bytes) -> dict:
        from .image import raw_to_bmp

        return self.print_image(raw_to_bmp(width, height, raw, top_down=True))

    # ------------------------------------------------------------------ #
    def _send(self, items: list[dict]) -> dict:
        print_id = _new_print_id()
        payload = {
            "command": 3,
            "content": {"textList": items},
            "encryptFlag": 0,
            "hasHead": 0,
            "hasSignature": 0,
            "hasTail": 0,
            "isFromDirectPrint": False,
            "msgType": 1,
            "pkgCount": 1,
            "pkgNo": 1,
            "printID": print_id,
            "priority": 0,
            "result": 0,
            "scripType": 3,
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        if len(raw) <= MAX_BODY:
            return self._request(payload, method="POST")

        # 大任务：按字节切分 basetext 不现实（图片是 base64 的 BMP），
        # 固件按 pkgNo/pkgCount 重组；这里把 textList 拆成多份发送。
        results = []
        per = max(1, len(items) // ((len(raw) // MAX_BODY) + 1))
        chunks = [items[i:i + per] for i in range(0, len(items), per)]
        for idx, chunk in enumerate(chunks, start=1):
            payload["content"] = {"textList": chunk}
            payload["pkgCount"] = len(chunks)
            payload["pkgNo"] = idx
            payload["printID"] = print_id
            results.append(self._request(payload, method="POST"))
        return results[-1] if results else {}


def discover(subnet_prefix: str | None = None, *, port: int = 80, timeout: float = 0.35) -> list[str]:
    """
    在局域网里扫 /sys/printer。未给 subnet_prefix 时用本机网段（x.y.z）。
    返回响应了 printerState 的 IP 列表。
    """
    import concurrent.futures

    if subnet_prefix is None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        subnet_prefix = ".".join(ip.split(".")[:3])

    def probe(i: int) -> str | None:
        host = f"{subnet_prefix}.{i}"
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
        except OSError:
            return None
        try:
            p = LanPrinter(host, port=port, timeout=1.5)
            st = p.status()
            if "printerState" in st or "command" in st:
                return host
        except (urllib.error.URLError, OSError, ValueError):
            return None
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        return [h for h in pool.map(probe, range(1, 255)) if h]
