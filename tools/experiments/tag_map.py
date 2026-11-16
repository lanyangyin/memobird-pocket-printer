#!/usr/bin/env python3
"""
tools/experiments/tag_map.py — 试探 cmd 0x03 的设置项 tag 映射（写 → 读状态 → 看哪项变了 → 还原）

    python tools/experiments/tag_map.py 00:15:83:E4:7A:F2 --tag 0x02 --value 5 --restore 10

策略：写一个 tag，然后读状态，对比「哪个状态字段变了」——变了就说明这个 tag
既是设置项、也能在状态里读到。最后写回原值。
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from memobird_printer import packet          # noqa: E402
from memobird_printer.ble import BlePrinter  # noqa: E402


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


async def read_status(b: BlePrinter, wait: float = 1.5, retries: int = 3) -> dict[int, bytes]:
    """优先用 cmd 0x0A 主动上报（设置后设备会推），拿不到就发 0x02 问。
    刚连上时第一次读常漏，所以重试几次。"""
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
    tag = int(args.tag, 0)
    value = int(args.value, 0)
    async with BlePrinter(args.address, echo=False) as b:
        before = await read_status(b, args.wait)
        print("写入前状态:")
        for t, v in sorted(before.items()):
            n = int.from_bytes(v, "little") if len(v) <= 2 else None
            print(f"  0x{t:02x} = {v.hex()}" + (f"  ({n})" if n is not None else ""))

        print(f"\n写入 cmd 0x03  tag=0x{tag:02x} value={value} …")
        await b.write(packet.build_frame(0x03, packet.tlv(tag, bytes([value & 0xFF]))))
        await asyncio.sleep(0.6)
        after = await read_status(b, args.wait)

        print("写入后状态:")
        for t, v in sorted(after.items()):
            n = int.from_bytes(v, "little") if len(v) <= 2 else None
            print(f"  0x{t:02x} = {v.hex()}" + (f"  ({n})" if n is not None else ""))

        print("\n变化项:")
        changed = False
        for t in sorted(set(before) | set(after)):
            a = before.get(t, b"\x00")
            c = after.get(t, b"\x00")
            if a != c:
                changed = True
                na = int.from_bytes(a, "little")
                nc = int.from_bytes(c, "little")
                guess = " <== 这个 tag 就是设置项本身" if t == tag else ""
                print(f"  0x{t:02x}: {na} → {nc}{guess}")
        if not changed:
            print("  （无变化：这个 tag 可能不是设置项，或者值超范围被忽略）")

        if args.restore is not None:
            rv = int(args.restore, 0)
            print(f"\n还原：cmd 0x03 tag=0x{tag:02x} value={rv}")
            await b.write(packet.build_frame(0x03, packet.tlv(tag, bytes([rv & 0xFF]))))
            await asyncio.sleep(0.6)
            back = await read_status(b, args.wait)
            for t in sorted(back):
                if back.get(t) != after.get(t):
                    print(f"  还原后 0x{t:02x} = {int.from_bytes(back[t], 'little')}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--value", required=True)
    ap.add_argument("--restore", default=None)
    ap.add_argument("--wait", type=float, default=1.5)
    sys.exit(asyncio.run(main(ap.parse_args())))
