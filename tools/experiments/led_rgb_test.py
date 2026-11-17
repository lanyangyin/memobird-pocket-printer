#!/usr/bin/env python3
"""试探 cmd 0x05/0x06/0x07 是不是 RGB 三色灯通道。

现象来源：分别往 0x05/0x06/0x07 写 20(0x14) 之后，指示灯从绿变白。
若三者是 R/G/B，那么：
    红   = (255, 0, 0)
    绿   = (0, 255, 0)
    蓝   = (0, 0, 255)
    白   = (255,255,255)
    灭   = (0, 0, 0)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from memobird_printer import packet          # noqa: E402
from memobird_printer.ble import BlePrinter  # noqa: E402


async def set_rgb(address: str, r: int, g: int, b: int) -> list[str]:
    out = []
    async with BlePrinter(address, echo=False) as dev:
        for cmd, val in ((0x05, r), (0x06, g), (0x07, b)):
            try:
                frames = await dev.transact(packet.build_frame(cmd, bytes([val])), wait=0.8, retries=1)
                out.append(frames[-1].hex(" ") if frames else "无回包")
            except Exception as exc:                       # noqa: BLE001
                out.append(f"失败:{type(exc).__name__}")
    return out


async def main(args) -> int:
    tests = [("红", 255, 0, 0), ("绿", 0, 255, 0), ("蓝", 0, 0, 255), ("白", 255, 255, 255)]
    for name, r, g, b in tests:
        print(f"{time.strftime('%H:%M:%S')} → {name} ({r},{g},{b})", flush=True)
        for reply in await set_rgb(args.address, r, g, b):
            print(f"            ← {reply}", flush=True)
        await asyncio.sleep(2.5)
    print("\n请观察灯：红/绿/蓝/白 依次出现过吗？")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    sys.exit(asyncio.run(main(ap.parse_args())))
