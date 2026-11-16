#!/usr/bin/env python3
"""
tools/_autooff_test.py — 严格验证 tag 0x02 是不是"自动关机时间（分钟）"

上次用"连接保持 + 静置"测不出结果：很多设备只要 BLE 连着就不计时。
这次改成：设 0x02=1 → **主动断开** → 等 100 秒 → 扫描看它还广播不广播。

    python tools/_autooff_test.py <地址> --minutes 1 --idle 100 --restore 10

结果解读：
  · 扫不到设备 → 已自动关机 ⇒ 0x02 就是自动关机时间（此时按键唤醒，再跑 --restore-only 还原）
  · 还能扫到   → 不是自动关机时间（0x02 另有含义）
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from memobird_printer import device           # noqa: E402
from memobird_printer.ble import BlePrinter   # noqa: E402


async def set_value(address: str, value: int) -> None:
    async with BlePrinter(address, echo=False) as b:
        frames = await b.transact(device.setting_frame(0x02, value), wait=1.0)
        print(f"  已写 0x02={value}，应答 {len(frames)} 帧")
        infos = await device.read_info(b, detail=False, wait=1.2)
        if infos:
            print(f"  读回 0x02 = {infos[-1].value(0x02)}")
        else:
            print("  （状态没读到，但命令已发出）")


async def scan_for(address: str, seconds: float) -> bool:
    from bleak import BleakScanner

    print(f"  扫描 {seconds:.0f}s …")
    found = await BleakScanner.discover(timeout=seconds)
    for d in found:
        if (d.address or "").upper() == address.upper():
            print(f"  找到 {d.name or '(无名)'} {d.address}  → 设备还醒着")
            return True
    print("  没有找到目标设备")
    return False


async def main(args) -> int:
    if args.restore_only:
        print(f"只还原 0x02 = {args.restore}")
        await set_value(args.address, args.restore)
        return 0

    print(f"1) 把 0x02 设为 {args.minutes} 分钟")
    await set_value(args.address, args.minutes)

    print(f"\n2) 断开 BLE，静置 {args.idle}s（模拟「用户走开」）")
    await asyncio.sleep(args.idle)

    print("\n3) 扫描看设备还在不在")
    online = await scan_for(args.address, 12)

    if online:
        print("\n结论：还醒着 → 0x02 不是自动关机时间（或该固件不用它）")
        print(f"还原 0x02 = {args.restore}")
        await set_value(args.address, args.restore)
    else:
        print("\n结论：扫不到 → 大概率已自动关机，0x02 ≈ 自动关机时间（分钟）")
        print("请按一下打印机按键唤醒它，然后运行：")
        print(f"  python tools/_autooff_test.py {args.address} --restore-only")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--minutes", type=int, default=1)
    ap.add_argument("--idle", type=int, default=100)
    ap.add_argument("--restore", type=int, default=10)
    ap.add_argument("--restore-only", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args())))
