#!/usr/bin/env python3
"""
tools/experiments/autooff_scan.py — 找"定时关机"设置项

已知：0x02 是打印浓度（不是关机时间），0x03 是指示灯。
所以关机时间要么在别的 tag 上，要么根本没有（固件固定）。

做法（只用已确认安全的 cmd 0x03 写设置）：
  对每个候选 tag 写一个值 → 读状态 → 看这个 tag 有没有出现在状态帧里
  出现了 ⇒ 它是设置项（固件接受了并记住）

    python tools/experiments/autooff_scan.py <地址> [--value 10]

注意：只测设置类 tag，**不碰**之前把 BLE 写崩的 cmd 0x05/0x06/0x07。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from memobird_printer import device, packet      # noqa: E402
from memobird_printer.ble import BlePrinter      # noqa: E402

# 只测这些（跳过已知：0x01 常量、0x02 浓度、0x03 灯、0x04 电压、0x06 缺纸、
# 0x0F 序列号、0x0E/0x13/0x14 状态位，也跳过 0x0B/0x0C/0x0D 打印计数器）
CANDIDATES = (0x07, 0x08, 0x09, 0x0A, 0x10, 0x11, 0x12)


async def read_info(dev: BlePrinter) -> device.DeviceInfo | None:
    frames = await dev.transact(device.status_frame(), wait=1.2)
    infos = [i for i in (device.parse_status(f) for f in frames) if i]
    return infos[-1] if infos else None


async def main(args) -> int:
    async with BlePrinter(args.address, echo=False) as dev:
        base = await read_info(dev)
        if not base:
            print("读不到状态，先唤醒设备")
            return 1
        print("基线 tag：", " ".join(f"0x{t:02x}={base.value(t)}" for t in sorted(base.fields)))
        known = set(base.fields)

        for tag in CANDIDATES:
            try:
                frame = device.setting_frame(tag, args.value)
            except ValueError as exc:
                print(f"0x{tag:02x}: 跳过（{exc}）")
                continue
            reply = await dev.transact(frame, wait=1.0, retries=1)
            await asyncio.sleep(0.4)
            info = await read_info(dev)
            if not info:
                print(f"0x{tag:02x}: 写完读不到状态")
                continue
            got = info.value(tag)
            if tag in known:
                print(f"0x{tag:02x}: 原本就有，写 {args.value} → 现在 {got}")
            elif tag in info.fields:
                print(f"0x{tag:02x}: ★ 新出现！值 = {got}  ⇒ 这是可写设置项")
            else:
                print(f"0x{tag:02x}: 无变化（固件忽略）  回包 {reply[-1].hex(' ') if reply else '无'}")

        print("\n提示：若找到新的可写 tag，下一步把它设成 1，断开静置 2 分钟再扫描 —— "
              "设备消失就说明那是关机时间。")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--value", type=int, default=10)
    sys.exit(asyncio.run(main(ap.parse_args())))
