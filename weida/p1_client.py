"""Dothantech P1 标签机 —— 免厂商 App 的 BLE 客户端（已在真机验证）

实测通过（2026-11-20，P1-61085930 / 28:D4:1E:9A:99:DB，固件 5.20）：

* 写数据：FF02（write without response），单片 20 字节
* 流控：FF03 通知 `01 nn` = 授予 nn 个信用额度；每写一片消耗 1 个
* 打印内容：**裸 ESC/POS**（`GS v 0` 光栅 + `ESC J` 走纸），不需要 AA/BB 帧
* AA/BB 帧只在"控制命令"时用（探测/查询），内容直接发字节流

用法：
    python p1_client.py info                       # 读型号/固件/序列号
    python p1_client.py demo                       # 打一张黑白格子测试图
    python p1_client.py print-png a.png --feed 32   # 打一张 PNG
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import weida_protocol as W  # noqa: E402

FF01 = "0000ff01-0000-1000-8000-00805f9b34fb"
FF02 = "0000ff02-0000-1000-8000-00805f9b34fb"
FF03 = "0000ff03-0000-1000-8000-00805f9b34fb"

INFO_UUIDS = {
    "厂商": "00002a29-0000-1000-8000-00805f9b34fb",
    "型号": "00002a24-0000-1000-8000-00805f9b34fb",
    "序列号": "00002a25-0000-1000-8000-00805f9b34fb",
    "固件": "00002a26-0000-1000-8000-00805f9b34fb",
    "硬件": "00002a27-0000-1000-8000-00805f9b34fb",
    "软件": "00002a28-0000-1000-8000-00805f9b34fb",
}

DEFAULT_CHUNK = 20
DEFAULT_SETTLE = 0.004


class P1Client:
    """P1 标签机 BLE 客户端（信用流控）。"""

    def __init__(self, addr: str, *, chunk: int = DEFAULT_CHUNK,
                 settle: float = DEFAULT_SETTLE, echo: bool = True):
        self.addr = addr
        self.chunk = chunk
        self.settle = settle
        self.echo = echo
        self.client = None
        self.credits = 0
        self.sent_bytes = 0
        self.messages: list[tuple[str, str]] = []
        self._cond = asyncio.Condition()
        self._loop = None

    # ---------------- 生命周期 ----------------
    async def __aenter__(self):
        from bleak import BleakClient

        self._loop = asyncio.get_running_loop()
        self.client = BleakClient(self.addr, timeout=25)
        for attempt in range(4):
            try:
                await self.client.connect()
                break
            except Exception:
                if attempt == 3:
                    raise
                await asyncio.sleep(1.5)
        await self.client.start_notify(FF03, self._on_ff03)
        try:
            await self.client.start_notify(FF01, self._on_ff01)
        except Exception:                            # noqa: BLE001
            pass
        await asyncio.sleep(1.2)                     # 等固件准备好 + 初始额度
        return self

    async def __aexit__(self, *exc):
        try:
            await self.client.disconnect()
        except Exception:                            # noqa: BLE001
            pass
        return False

    def _log(self, text: str, chan: str = "") -> None:
        self.messages.append((chan, text))
        if self.echo:
            print(f"    <- {chan} {text}", flush=True)

    def _on_ff03(self, _sender, data: bytearray) -> None:
        raw = bytes(data)
        self._log(raw.hex(" "), "FF03")
        if len(raw) >= 2 and raw[0] == 0x01:
            # 在事件循环里改额度
            self._loop.create_task(self._grant(raw[1]))

    def _on_ff01(self, _sender, data: bytearray) -> None:
        self._log(bytes(data).hex(" "), "FF01")

    async def _grant(self, n: int) -> None:
        async with self._cond:
            self.credits += n
            self._cond.notify_all()

    # ---------------- 发送 ----------------
    async def send(self, data: bytes, *, timeout: float = 8.0) -> bool:
        """按信用额度分片发送。"""
        for i in range(0, len(data), self.chunk):
            piece = data[i:i + self.chunk]
            deadline = time.time() + timeout
            async with self._cond:
                while self.credits <= 0 and time.time() < deadline:
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=0.3)
                    except asyncio.TimeoutError:
                        pass
                if self.credits <= 0:
                    if self.echo:
                        print(f"    ⚠ 等额度超时（已发 {self.sent_bytes} 字节）", flush=True)
                    return False
                self.credits -= 1
            try:
                await self.client.write_gatt_char(FF02, piece, response=False)
            except Exception:                        # noqa: BLE001
                await self.client.write_gatt_char(FF02, piece, response=True)
            self.sent_bytes += len(piece)
            if self.settle:
                await asyncio.sleep(self.settle)
        return True

    async def send_cmd(self, cmd: int, payload: bytes = b"") -> bool:
        """发一条控制命令（AA/BB 帧），走同一条信用通道。"""
        return await self.send(W.frame(cmd, payload))

    # ---------------- 便捷操作 ----------------
    async def read_info(self) -> dict:
        out = {}
        for label, uuid in INFO_UUIDS.items():
            try:
                val = bytes(await self.client.read_gatt_char(uuid))
                out[label] = val.decode("utf-8", "replace").strip("\x00 ")
            except Exception as exc:                 # noqa: BLE001
                out[label] = f"<{type(exc).__name__}>"
        return out

    async def print_1bpp(self, raw: bytes, width_dots: int, height_dots: int,
                         *, feed_dots: int = 24) -> bool:
        stream = W.job_from_1bpp(raw, width_dots, height_dots, line_dots=feed_dots)
        if self.echo:
            print(f"    发送 {len(stream)} 字节（{width_dots}x{height_dots} 光栅）", flush=True)
        return await self.send(stream)

    async def print_png(self, path: str, *, width_dots: int = 384,
                        threshold: int = 128, feed_dots: int = 24) -> bool:
        from PIL import Image

        img = Image.open(path).convert("L")
        ratio = width_dots / img.width
        img = img.resize((width_dots, max(1, int(img.height * ratio))))
        px = img.load()
        row = (width_dots + 7) // 8
        raw = bytearray(row * img.height)
        for y in range(img.height):
            for x in range(width_dots):
                if px[x, y] < threshold:
                    raw[y * row + (x >> 3)] |= 0x80 >> (x & 7)
        return await self.print_1bpp(bytes(raw), width_dots, img.height, feed_dots=feed_dots)


# --------------------------------------------------------------------------- #
def _demo_image(width: int = 384, height: int = 40) -> tuple[bytes, int, int]:
    row = (width + 7) // 8
    raw = bytearray(row * height)
    for y in range(height):
        for x in range(width):
            if (x // 16 + y // 8) % 2 == 0:
                raw[y * row + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(raw), width, height


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dothantech P1 BLE 客户端")
    ap.add_argument("what", nargs="?", default="demo",
                    choices=["info", "demo", "print-png", "cmd"])
    ap.add_argument("arg", nargs="?", help="print-png 的路径 / cmd 的命令码")
    ap.add_argument("--addr", default="28:D4:1E:9A:99:DB")
    ap.add_argument("--feed", type=int, default=24, help="打完走纸多少点")
    ap.add_argument("--width", type=int, default=384, help="打印宽度（点）")
    ap.add_argument("--threshold", type=int, default=128)
    args = ap.parse_args(argv)

    if not args.addr:
        print("需要 --addr 或先扫描")
        return 2

    async with P1Client(args.addr) as p1:
        if args.what == "info":
            info = await p1.read_info()
            for k, v in info.items():
                print(f"  {k}: {v}")
            return 0

        if args.what == "cmd":
            code = int(args.arg, 0) if args.arg else 0x79
            ok = await p1.send_cmd(code)
            print(f"  命令 0x{code:02X} 发送{'成功' if ok else '失败'}")
            await asyncio.sleep(1.0)
            return 0

        if args.what == "print-png":
            if not args.arg:
                print("print-png 需要图片路径")
                return 2
            ok = await p1.print_png(args.arg, width_dots=args.width,
                                    threshold=args.threshold, feed_dots=args.feed)
        else:
            raw, w, h = _demo_image(args.width, 40)
            ok = await p1.print_1bpp(raw, w, h, feed_dots=args.feed)

        print(f"  结果: {'已发送 ' + str(p1.sent_bytes) + ' 字节' if ok else '发送中断'}")
        await asyncio.sleep(1.5)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
