#!/usr/bin/env python3
"""
tools/experiments/drain_test.py — 区分「电量」还是「温度」：打两张全黑图，看状态字段怎么动

判据：
  · 打印头满负荷会**发热** → 若某字段跳高、之后慢慢回落 ⇒ 那是温度
  · 打印是最耗电的动作   → 若某字段小幅下掉、之后缓慢回升 ⇒ 那是电压/电量

    python tools/experiments/drain_test.py <地址> [--pages 2] [--cool 6]
"""
from __future__ import annotations

import argparse
import asyncio
import io
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

from PIL import Image                                   # noqa: E402

from memobird_printer import device, packet             # noqa: E402
from memobird_printer.ble import BlePrinter             # noqa: E402
from memobird_printer.image import dither_to_raw, raw_to_bmp   # noqa: E402


def snapshot(info: device.DeviceInfo) -> str:
    parts = []
    for tag in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x13):
        v = info.value(tag)
        parts.append(f"0x{tag:02x}={v}")
    return "  ".join(parts)


async def read(b: BlePrinter) -> device.DeviceInfo | None:
    for _ in range(2):
        frames = await b.transact(device.status_frame(), wait=1.2)
        infos = [info for info in (device.parse_status(f) for f in frames) if info]
        if infos:
            return infos[-1]
    return None


def make_job(shade: int, h: int = 300):
    """生成一页：shade=0 全黑（最耗电），255 全白，128 半黑"""
    img = Image.new("L", (384, h), shade)
    w, hh, raw = dither_to_raw(img, "threshold")
    bmp = raw_to_bmp(w, hh, raw, official=True)
    return packet.build_bmp_job(bmp)


async def connect(address: str) -> BlePrinter:
    b = BlePrinter(address, echo=False)
    await b.__aenter__()
    return b


async def safe_send(b: BlePrinter, address: str, frames, *, preheat: bool = True):
    """发一页；掉线就重连再试一次。返回 (是否成功, 当前连接)"""
    try:
        await b.send_frames(frames, preheat=preheat, inter_frame=0.01)
        return True, b
    except Exception as exc:                                  # noqa: BLE001
        print(f"   !! 打印中断（{type(exc).__name__}: {exc}）→ 重连后重试一次")
        try:
            await b.__aexit__()
        except Exception:
            pass
        try:
            b2 = await connect(address)
            await b2.send_frames(frames, preheat=preheat, inter_frame=0.01)
            return True, b2
        except Exception as exc2:                             # noqa: BLE001
            print(f"   !! 重试也失败（{type(exc2).__name__}: {exc2}）")
            return False, None


async def main(args) -> int:
    b = await connect(args.address)
    try:
        base = await read(b)
        print(f"{time.strftime('%H:%M:%S')} 打印前 : {snapshot(base) if base else '读不到'}")

        job = make_job(args.shade, args.height)
        for i in range(1, args.pages + 1):
            t0 = time.time()
            ok, b = await safe_send(b, args.address, job.frames)
            if not ok or b is None:
                print("   放弃本次测试（连接不稳）")
                return 1
            await asyncio.sleep(args.settle)
            info = await read(b)
            print(f"{time.strftime('%H:%M:%S')} 第{i}张后: {snapshot(info) if info else '读不到'}"
                  f"   (发送 {time.time() - t0:.1f}s)")
            if args.pause:
                await asyncio.sleep(args.pause)

        print(f"\n冷却观察（每 {args.interval}s 一次，共 {args.cool} 次）")
        for i in range(args.cool):
            await asyncio.sleep(args.interval)
            info = await read(b)
            print(f"{time.strftime('%H:%M:%S')} 冷却{i + 1}: {snapshot(info) if info else '读不到'}")
    finally:
        try:
            await b.__aexit__()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--height", type=int, default=300)
    ap.add_argument("--settle", type=float, default=1.0, help="打完等多久再读")
    ap.add_argument("--shade", type=int, default=0, help="灰度 0=全黑 128=半黑 255=全白")
    ap.add_argument("--pause", type=float, default=0.0, help="两页之间停顿")
    ap.add_argument("--cool", type=int, default=6, help="冷却观察次数")
    ap.add_argument("--interval", type=float, default=20.0)
    sys.exit(asyncio.run(main(ap.parse_args())))
