#!/usr/bin/env python3
"""
tools/experiments/reverse_feed.py — 试探"退纸/回纸"命令

先正向走 10mm（给出可回收的余量），再逐个发未解命令（0x05/0x06/0x07/0x08），
每条命令用**独立连接**（设备忙时会踢掉长连接），之间停 2 秒并打印时间戳 ——
人盯着纸，看哪一下纸往回缩。

    python tools/experiments/reverse_feed.py <地址>

判据：
  * 某条命令后纸明显回缩            ⇒ 找到退纸命令
  * 某条命令后纸又向前走            ⇒ 那是正向走纸命令（也有用）
  * 完全没反应                      ⇒ 这台固件不支持退纸（常见：单向纸路）
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

from memobird_printer import packet                      # noqa: E402
from memobird_printer.ble import BlePrinter               # noqa: E402
from memobird_printer.paper import blank_frames           # noqa: E402

CANDIDATES = (0x05, 0x06, 0x07, 0x08)


async def feed_10mm(address: str) -> bool:
    for _ in range(2):
        try:
            async with BlePrinter(address, echo=False) as b:
                frames, _ = blank_frames(mm=10, tick=True)
                await b.send_frames(frames, preheat=True, inter_frame=0.01)
                return True
        except Exception as exc:                              # noqa: BLE001
            print(f"   (走纸失败：{type(exc).__name__}: {exc})")
            await asyncio.sleep(1.5)
    return False


async def send_once(address: str, cmd: int, payload: bytes) -> list[bytes]:
    for _ in range(2):
        try:
            async with BlePrinter(address, echo=False) as b:
                return await b.transact(packet.build_frame(cmd, payload), wait=1.0, retries=1)
        except Exception as exc:                              # noqa: BLE001
            print(f"   (发送失败：{type(exc).__name__}: {exc})")
            await asyncio.sleep(1.2)
    return []


async def main(args) -> int:
    print(f"{time.strftime('%H:%M:%S')} 先正向走纸 10mm（给出可回收的余量）…")
    ok = await feed_10mm(args.address)
    print(f"{time.strftime('%H:%M:%S')} 走纸{'完成' if ok else '失败'}")
    await asyncio.sleep(2.5)

    for cmd in CANDIDATES:
        for payload in (b"", b"\x01", b"\x14"):
            label = f"0x{cmd:02x} payload={payload.hex() or '(空)'}"
            print(f"{time.strftime('%H:%M:%S')} → {label}", flush=True)
            frames = await send_once(args.address, cmd, payload)
            reply = frames[-1].hex(" ") if frames else "（无回包）"
            print(f"            ← {reply}", flush=True)
            await asyncio.sleep(1.8)

    print(f"\n{time.strftime('%H:%M:%S')} 试探结束。对照上面的时间戳，哪一条让纸回缩了？")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    sys.exit(asyncio.run(main(ap.parse_args())))
