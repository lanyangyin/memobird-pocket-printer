"""P1 串口客户端（经典蓝牙 SPP / USB 串口）—— 与 BLE 客户端同一套 API。

用途：电脑上通过蓝牙 SPP 或 USB 线控制打印机，不需要 BLE 信用流控。

用法：
    python p1_serial.py info
    python p1_serial.py status
    python p1_serial.py settings
    python p1_serial.py print-text "你好" --port COM64
    python p1_serial.py print-qr "https://example.com"
    python p1_serial.py print-png a.png
    python p1_serial.py print-label a.png --count 3
    python p1_serial.py ports            # 列出可能的打印机串口
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
from p1_client import (GAP_TYPES, P1Client, render_qr, render_text,  # noqa: E402
                       DEFAULT_CHUNK)


class P1SerialClient(P1Client):
    """串口版客户端：同一个 API，底层换成 COM 口。"""

    def __init__(self, port: str, *, baudrate: int = 115200, echo: bool = True,
                 timeout: float = 3.0):
        super().__init__(port, echo=echo)
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.reader = W.FrameReader()
        self._read_task: asyncio.Task | None = None
        self._closing = False

    async def __aenter__(self):
        import serial

        self._loop = asyncio.get_running_loop()
        self.ser = serial.Serial(self.port, self.baudrate,
                                 timeout=0.2, write_timeout=3)
        self.ser.reset_input_buffer()
        self._read_task = asyncio.create_task(self._read_loop())
        await asyncio.sleep(0.25)
        try:
            await self.send_cmd(W.CMD_ENABLE_SETTING, b"\x7f")
            await asyncio.sleep(0.2)
        except Exception:                            # noqa: BLE001
            pass
        return self

    async def __aexit__(self, *exc):
        self._closing = True
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        try:
            self.ser.close()
        except Exception:                            # noqa: BLE001
            pass
        return False

    async def _read_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._closing:
            try:
                chunk = await loop.run_in_executor(None, self.ser.read, 256)
            except Exception:                        # noqa: BLE001
                return
            if not chunk:
                continue
            for cmd, payload in self.reader.feed(chunk):
                self.rxq.append((cmd, payload))
                if self.echo:
                    print(f"    <- {cmd:02X} {payload.hex(' ')}", flush=True)
                if cmd == W.CMD_PUSH_STATUS:
                    self.push_status.append(W.decode_push(payload))
                if self._waiter is not None and not self._waiter.done():
                    self._waiter.set_result((cmd, payload))

    async def send(self, data: bytes, *, timeout: float = 8.0) -> bool:
        """串口没有信用额度，直接写。"""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._write, data)
        except Exception as exc:                     # noqa: BLE001
            if self.echo:
                print(f"    ⚠ 串口写入失败：{type(exc).__name__}", flush=True)
            return False
        self.sent_bytes += len(data)
        return True

    def _write(self, data: bytes) -> None:
        self.ser.write(data)
        self.ser.flush()

    async def connect(self):
        return self

    async def disconnect(self):
        await self.__aexit__()


def list_ports() -> int:
    import serial.tools.list_ports as lp

    found = []
    for p in lp.comports():
        hwid = p.hwid or ""
        # 蓝牙 SPP 端口；已知打印机 MAC 优先
        if "00001101-0000-1000-8000-00805F9B34FB" in hwid.upper():
            found.append((p.device, p.description, hwid))
    if not found:
        print("  没有蓝牙串口。先在 Windows 设置里把打印机配对。")
        return 1
    print("  蓝牙串口：")
    for dev, desc, hwid in found:
        # hwid 形如 ...&0&001583E47AF2_C00000000，取中间那段 12 位 MAC
        mac = ""
        tail = hwid.rsplit("&0&", 1)[-1]
        head = tail.split("_")[0]
        if len(head) == 12 and all(c in "0123456789ABCDEFabcdef" for c in head):
            mac = ":".join(head[i:i + 2] for i in range(0, 12, 2)).upper()
        print(f"    {dev:7s} {desc}  MAC={mac or '?'}")
    print("\n  用 --port COMxx 指定；P1 的 MAC 是 28D41E9A99DB")
    return 0


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P1 串口客户端")
    ap.add_argument("what", nargs="?", default="status",
                    choices=["info", "status", "settings", "print-text", "print-qr",
                             "print-png", "print-label", "cmd", "ports"])
    ap.add_argument("arg", nargs="?", help="文本 / 图片路径 / 命令码")
    ap.add_argument("--port", default="COM64")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--label-h", type=int, default=240)
    args = ap.parse_args(argv)

    if args.what == "ports":
        return list_ports()

    async with P1SerialClient(args.port, baudrate=args.baud, echo=False) as p1:
        if args.what == "info":
            info = await p1.read_info()
            for k, v in info.items():
                print(f"  {k}: {v}")
            return 0

        if args.what == "status":
            st = await p1.status()
            print(f"  状态: {st.get('text')}  (code={st.get('code')})")
            bat = await p1.battery()
            if bat.get("ok"):
                print(f"  电量: {bat['battery_v']}V  格数={bat.get('battery_level')}"
                      f"{'  充电中' if bat.get('charging') else ''}")
            t = await p1.head_temp()
            if t.get("ok"):
                print(f"  打印头: {t['head_temp_c']}°C")
            return 0

        if args.what == "settings":
            import json
            print(json.dumps(await p1.settings(), ensure_ascii=False, indent=2))
            return 0

        if args.what == "cmd":
            code = int(args.arg, 0) if args.arg else 0x70
            r = await p1.query(code)
            print(f"  0x{code:02X} → {r[1].hex(' ') if r else '无回包'}")
            return 0

        if args.what == "print-text":
            ok = await p1.print_text(args.arg or "Hello P1")
        elif args.what == "print-qr":
            ok = await p1.print_qr(args.arg or "https://example.com", caption=args.arg or "")
        elif args.what == "print-png":
            if not args.arg:
                print("print-png 需要图片路径")
                return 2
            ok = await p1.print_png(args.arg, width_dots=args.width)
        else:
            if not args.arg:
                print("print-label 需要图片路径")
                return 2
            from PIL import Image

            img = Image.open(args.arg).convert("L")
            ratio = min(args.width / img.width, args.label_h / img.height)
            img = img.resize((max(1, int(img.width * ratio)),
                              max(1, int(img.height * ratio))))
            row_bytes = (args.width + 7) // 8
            canvas = bytearray(row_bytes * args.label_h)
            ox, oy = (args.width - img.width) // 2, (args.label_h - img.height) // 2
            px = img.load()
            for y in range(img.height):
                for x in range(img.width):
                    if px[x, y] < 128:
                        gx, gy = ox + x, oy + y
                        canvas[gy * row_bytes + (gx >> 3)] |= 0x80 >> (gx & 7)
            if args.count > 1:
                n = await p1.print_batch(bytes(canvas), args.width, args.label_h,
                                         args.count, width_mm=args.width // 8)
                print(f"  结果: {n}/{args.count} 张，共 {p1.sent_bytes} 字节")
                return 0 if n == args.count else 1
            ok = await p1.print_label_1bpp(bytes(canvas), args.width, args.label_h,
                                           width_mm=args.width // 8, align_first=True)

        print(f"  结果: {'已发送 ' + str(p1.sent_bytes) + ' 字节' if ok else '中断'}")
        await asyncio.sleep(1.5)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
