#!/usr/bin/env python3
"""
tools/experiments/sleep_test.py — 验证 tag 0x02 是不是"自动关机/休眠时间（分钟）"

做法：把 0x02 设成 1 → 静置 80 秒（不发任何 BLE 数据，避免把它"叫醒"）
     → 再试读状态：
        读得到 = 没睡（0x02 不是自动关机，或计时被连接本身重置）
        读不到/连接断 = 基本确认 0x02 = 自动关机分钟数

    python tools/experiments/sleep_test.py <地址> [--minutes 1] [--idle 80] [--restore 10]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from memobird_printer import packet           # noqa: E402
from memobird_printer.ble import BlePrinter   # noqa: E402


def tlvs(payload: bytes) -> dict[int, bytes]:
    out, i = {}, 0
    while i + 3 <= len(payload):
        tag = payload[i]
        ln = payload[i + 1] | (payload[i + 2] << 8)
        if i + 3 + ln > len(payload):
            break
        out[tag] = payload[i + 3:i + 3 + ln]
        i += 3 + ln
    return out


async def read(b: BlePrinter, wait: float = 2.0, retries: int = 3) -> dict[int, bytes]:
    for attempt in range(retries):
        b._notifies.clear()
        await b.write(packet.build_frame(0x02))
        await asyncio.sleep(wait + 0.3 * attempt)
        for f in list(b._notifies):
            parsed = packet.parse_frame(f)
            if parsed and parsed[0] in (0x02, 0x0A):
                tl = tlvs(parsed[1])
                if tl:
                    return tl
    return {}


async def main(args) -> int:
    async with BlePrinter(args.address, echo=False) as b:
        st = await read(b)
        print(f"当前状态: " + " ".join(f"0x{t:02x}={int.from_bytes(v, 'little')}"
                                       for t, v in sorted(st.items()) if len(v) <= 2))
        print(f"\n把 0x02 设为 {args.minutes}（假设单位=分钟）…")
        await b.write(packet.build_frame(0x03, packet.tlv(0x02, bytes([args.minutes & 0xFF]))))
        await asyncio.sleep(0.8)
        st2 = await read(b)
        got = st2.get(0x02)
        print(f"设置后 0x02 = {int.from_bytes(got, 'little') if got else '?'}"
              f"  {'(确认可写)' if got and int.from_bytes(got, 'little') == args.minutes else '(没变?!)'}")

        print(f"\n静置 {args.idle}s，期间不发任何数据 …")
        for i in range(args.idle, 0, -1):
            if i % 20 == 0 or i <= 5:
                print(f"  还剩 {i}s")
            await asyncio.sleep(1)

        print("\n静置结束，尝试读状态 …")
        try:
            st3 = await read(b, wait=2.0, retries=2)
        except Exception as exc:                          # noqa: BLE001
            print(f"  读取异常：{type(exc).__name__}: {exc}")
            print("  → 很可能已经自动关机（或断连）。0x02 大概率就是自动关机时间。")
            return 0

        if st3:
            print("  仍然在线 → 0x02 不是自动关机时间，或者计时器被 BLE 连接本身重置")
        else:
            print("  没有回包 → 设备可能已休眠/关机（也可能是被别的连接打断）")

        if args.restore is not None:
            print(f"\n还原 0x02 = {args.restore}")
            try:
                await b.write(packet.build_frame(0x03, packet.tlv(0x02, bytes([args.restore & 0xFF]))))
                await asyncio.sleep(0.8)
                back = await read(b)
                v = back.get(0x02)
                print(f"  还原后 0x02 = {int.from_bytes(v, 'little') if v else '?'}")
            except Exception as exc:                      # noqa: BLE001
                print(f"  还原失败（设备已断）：{exc}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--minutes", type=int, default=1)
    ap.add_argument("--idle", type=int, default=80)
    ap.add_argument("--restore", type=int, default=10)
    sys.exit(asyncio.run(main(ap.parse_args())))
