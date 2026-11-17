#!/usr/bin/env python3
"""
tools/experiments/sleep_timer.py — 实测"多久自动关机"

不连设备，只扫描：设备某次扫描还在、下一次不在了 ⇒ 那就是它自己关机的时刻。

    python tools/experiments/sleep_timer.py 00:15:83:E4:7A:F2 --interval 30 --hours 1

判据：
  * 记录"最后一次扫到的时间"，跟你最后一次操作的时间相减 ≈ 自动关机时长
  * 期间不要连它（连接会让它保持唤醒）
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def scan_once(target: str, timeout: float = 6.0) -> bool:
    """扫一次，返回目标是否在广播"""
    from bleak import BleakScanner

    found = {"hit": False}

    def cb(dev, adv):
        if dev.address.upper() == target.upper():
            found["hit"] = True

    async def run():
        scanner = BleakScanner(detection_callback=cb)
        await scanner.start()
        try:
            await asyncio.sleep(timeout)
        finally:
            await scanner.stop()

    asyncio.run(run())
    return found["hit"]


def main(args) -> int:
    start = datetime.datetime.now()
    print(f"{start:%H:%M:%S} 开始监视 {args.address}（每 {args.interval}s 扫一次）")
    print("  提示：别连它，也别按键，否则会重新计时")
    last_seen = start
    checks = int(args.hours * 3600 / args.interval)
    for i in range(checks):
        hit = scan_once(args.address)
        now = datetime.datetime.now()
        if hit:
            last_seen = now
            print(f"{now:%H:%M:%S} 在广播（已静置 {(now - start).seconds // 60} 分钟）")
        else:
            idle = (now - last_seen).seconds
            print(f"{now:%H:%M:%S} ✗ 扫不到了 —— 最后一次扫到是 {last_seen:%H:%M:%S}，"
                  f"静置约 {idle // 60} 分 {idle % 60} 秒")
            print(f"  ⇒ 自动关机时间 ≈ {idle // 60} 分 {idle % 60} 秒（从最后一次活动算起）")
            return 0
        time.sleep(args.interval)
    print("监视结束，设备一直没关机")
    return 0


if __name__ == "__main__":
    import time

    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--hours", type=float, default=1.0)
    sys.exit(main(ap.parse_args()))
