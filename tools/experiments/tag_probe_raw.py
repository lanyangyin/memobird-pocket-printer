#!/usr/bin/env python3
"""
tools/experiments/tag_probe_raw.py — 绕过白名单，直接试探未知的设置 tag

用 **cmd 0x03**（官方"写设置"命令）逐个小值写入 tag 0x07..0x12，
每次写完立刻读状态：
  * 新 tag 出现在状态帧里 → 它是可写设置项
  * 设备读不到状态       → 立刻停（说明写坏了，需断电重启）

    python tools/experiments/tag_probe_raw.py <地址> [--value 1]

⚠️ 已知事故：之前对 **cmd 0x05/0x06/0x07** 写 20/255 把 BLE 写崩过（需断电重启）。
   本脚本只走 cmd 0x03（写设置）这条路，风险低得多，但仍建议人在旁边。
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

CANDIDATES = (0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x10, 0x11, 0x12)


async def read_info(dev: BlePrinter):
    frames = await dev.transact(device.status_frame(), wait=1.2)
    infos = [i for i in (device.parse_status(f) for f in frames) if i]
    return infos[-1] if infos else None


async def main(args) -> int:
    async with BlePrinter(args.address, echo=False) as dev:
        base = await read_info(dev)
        if not base:
            print("读不到状态，先唤醒设备")
            return 1
        known = dict(base.fields)
        print("基线：", " ".join(f"0x{t:02x}={base.value(t)}" for t in sorted(known)))

        for tag in CANDIDATES:
            frame = packet.build_frame(packet.CMD_CONTROL, packet.tlv(tag, bytes([args.value])))
            try:
                await dev.transact(frame, wait=0.8, retries=1)
            except Exception as exc:                       # noqa: BLE001
                print(f"0x{tag:02x}: 写入失败（{type(exc).__name__}）—— 停止")
                return 1
            await asyncio.sleep(0.3)
            info = await read_info(dev)
            if info is None:
                print(f"0x{tag:02x}: ⚠ 写完读不到状态 —— 设备可能卡住，停止！"
                      f"\n        需要断电重启（长按电源键）")
                return 1
            if tag in known:
                print(f"0x{tag:02x}: 已存在，写 {args.value} → 现在 {info.value(tag)}")
            elif tag in info.fields:
                print(f"0x{tag:02x}: ★ 新出现！值 = {info.value(tag)} ⇒ 可写设置项")
            else:
                print(f"0x{tag:02x}: 无变化（固件忽略）")
        print("\n扫描完成，设备正常。")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--value", type=int, default=1)
    sys.exit(asyncio.run(main(ap.parse_args())))
