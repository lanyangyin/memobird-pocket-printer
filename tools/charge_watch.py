#!/usr/bin/env python3
"""
tools/charge_watch.py — 长时间采样设备状态（每次采样独立连接，掉线也不中断）

用来做「充电/放电曲线」这类慢实验：电量百分比通常几分钟才动一格，
所以需要隔几分钟采一次、连续几十分钟。

    python tools/charge_watch.py 00:15:83:E4:7A:F2 --samples 20 --interval 120
    python tools/charge_watch.py <地址> --samples 30 --interval 60 --csv charge.csv

输出：控制台表格 + CSV（时间、0x01、0x02、0x03、0x04、0x05、0x06、0x13、在线）
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from memobird_printer import device            # noqa: E402
from memobird_printer.ble import BlePrinter    # noqa: E402

TAGS = (0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x13)


async def sample_once(address: str, wait: float = 1.5, retries: int = 2) -> device.DeviceInfo | None:
    """一次采样 = 一次独立连接（避免长时间持有连接被固件踢掉）。

    频繁连接时 Windows 偶发 "Characteristic ... was not found"（GATT 还没被发现完），
    重连一次就好了，所以这里带重试。
    """
    for attempt in range(retries):
        try:
            async with BlePrinter(address, echo=False) as b:
                frames = await b.transact(device.status_frame(), wait=wait)
                infos = [info for info in (device.parse_status(f) for f in frames) if info]
                if infos:
                    return infos[-1]
        except Exception as exc:                              # noqa: BLE001
            if attempt == retries - 1:
                print(f"   (采样失败：{type(exc).__name__}: {exc})")
    return None


async def main(args) -> int:
    rows: list[list] = []
    header = ["time", *[f"0x{t:02x}" for t in TAGS], "online"]
    print("时间         " + "  ".join(f"0x{t:02x}" for t in TAGS) + "  在线")
    offline = 0
    last_vals = None

    for i in range(args.samples):
        info = await sample_once(args.address, args.wait)
        t = time.strftime("%H:%M:%S")
        vals = [info.value(t) if info else None for t in TAGS]
        online = info is not None
        offline = 0 if online else offline + 1

        changed = last_vals is not None and vals != last_vals
        if (not args.changes_only) or last_vals is None or changed or not online:
            mark = "★ " if changed else "  "
            print(f"{mark}{t}   " + "  ".join(f"{'-' if v is None else v:>4}" for v in vals)
                  + f"   {'✓' if online else '✗'}", flush=True)
            if changed:
                for idx, tag in enumerate(TAGS, start=1):
                    if last_vals[idx - 1] != vals[idx - 1]:
                        print(f"     Δ 0x{tag:02x}: {last_vals[idx - 1]} → {vals[idx - 1]}", flush=True)
        last_vals = vals
        rows.append([t, *vals, online])
        if args.csv:
            new_file = not os.path.exists(args.csv)
            with open(args.csv, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(header)
                w.writerow(rows[-1])

        if offline >= 3:
            print("\n连续 3 次采样都连不上 —— 设备可能已关机。请按键唤醒 / 插上充电线后重跑。")
            break
        if i < args.samples - 1:
            await asyncio.sleep(args.interval)

    if args.csv and rows:
        print(f"\n已逐行写入 {args.csv}（{len(rows)} 行）")

    online_rows = [r for r in rows if r[-1]]
    if len(online_rows) >= 2:
        first, last = online_rows[0], online_rows[-1]
        print("\n首尾对比：")
        changed = False
        for idx, tag in enumerate(TAGS, start=1):
            a, b = first[idx], last[idx]
            if a != b:
                changed = True
                print(f"  0x{tag:02x}: {a} → {b}  (变化 {b - a:+d})")
        if not changed:
            print("  所有字段都没变（这段时间内没有可观察的变化）")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--interval", type=float, default=120.0, help="两次采样间隔（秒）")
    ap.add_argument("--wait", type=float, default=1.5)
    ap.add_argument("--csv", default="")
    ap.add_argument("--changes-only", action="store_true", help="只在状态变化时打印")
    sys.exit(asyncio.run(main(ap.parse_args())))
