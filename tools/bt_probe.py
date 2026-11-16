#!/usr/bin/env python3
"""
tools/bt_probe.py — 直连打印机做协议探测（只读优先）

在**有蓝牙适配器的电脑**上跑，不经过手机/浏览器：

    python tools/bt_probe.py scan                     # 扫附近的 BLE 设备
    python tools/bt_probe.py gatt  <地址>              # 打印 GATT 表
    python tools/bt_probe.py info  <地址>              # 发 cmd 0x01 读状态并解析 TLV
    python tools/bt_probe.py cmd   <地址> 01           # 发任意命令（payload 十六进制可选）
    python tools/bt_probe.py sweep <地址>              # 依次发 0x01..0x08，看哪些有回包

地址在 Windows 上是 bleak 的 device id（扫描输出里那串），Linux 是 MAC。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections import OrderedDict

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from memobird_printer import packet      # noqa: E402
from memobird_printer.ble import CHR_NOTIFY, CHR_WRITE   # noqa: E402

NAME_HINTS = ("gt1", "memobird", "gugu", "printer", "口袋", "咕咕")


def hexs(b: bytes) -> str:
    return " ".join(f"{x:02x}" for x in b)


def decode_tlvs(payload: bytes) -> list[tuple[int, bytes]]:
    out = []
    i = 0
    while i + 3 <= len(payload):
        tag = payload[i]
        ln = payload[i + 1] | (payload[i + 2] << 8)
        if i + 3 + ln > len(payload):
            break
        out.append((tag, payload[i + 3:i + 3 + ln]))
        i += 3 + ln
    return out


# --------------------------------------------------------------------------- #
async def cmd_scan(args) -> int:
    from bleak import BleakScanner

    print(f"扫描 {args.timeout}s …")
    found = await BleakScanner.discover(timeout=args.timeout)
    rows = []
    for d in found:
        name = d.name or ""
        low = name.lower()
        hit = any(h in low for h in NAME_HINTS)
        meta = getattr(d, "metadata", None) or {}          # bleak >=0.21 才有
        rows.append((hit, name, d.address, getattr(d, "rssi", None), meta, getattr(d, "details", None)))
    rows.sort(key=lambda r: (not r[0], -(r[3] or -999)))
    for hit, name, addr, rssi, man, details in rows:
        mark = " <== 疑似打印机" if hit else ""
        print(f"  {'*' if hit else ' '} {name or '(无名)':<24} {addr}  rssi={rssi}{mark}")
        if hit:
            if man.get("manufacturer_data"):
                print(f"      厂商数据: { {k: v.hex() for k, v in man['manufacturer_data'].items()} }")
            if details:
                print(f"      details: {details}")
    if not any(r[0] for r in rows):
        print("\n没找到名字像打印机的设备 —— 可能没开机/没在广播/已被别处连接")
    return 0


async def cmd_gatt(args) -> int:
    from bleak import BleakClient

    async with BleakClient(args.address, timeout=20) as dev:
        print(f"已连接 {dev.address}")
        for svc in dev.services:
            print(f"service {svc.uuid}")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                print(f"   chr {ch.uuid}  handle={ch.handle}  [{props}]")
                for d in ch.descriptors:
                    print(f"      desc {d.uuid}")
    return 0


class Link:
    """最小连接封装：发帧 + 收集 notify"""

    def __init__(self, address: str):
        self.address = address
        self.bufs: list[tuple[float, bytes]] = []
        self.client = None

    async def __aenter__(self):
        from bleak import BleakClient

        self.client = BleakClient(self.address, timeout=20)
        await self.client.connect()
        try:
            await self.client.start_notify(CHR_NOTIFY, self._on_notify)
        except Exception as exc:                       # noqa: BLE001
            print(f"  订阅通知失败: {exc}")
        return self

    async def __aexit__(self, *exc):
        try:
            await self.client.stop_notify(CHR_NOTIFY)
        except Exception:
            pass
        await self.client.disconnect()

    def _on_notify(self, _sender, data: bytearray):
        self.bufs.append((time.time(), bytes(data)))

    async def send(self, frame: bytes) -> None:
        try:
            await self.client.write_gatt_char(CHR_WRITE, frame, response=False)
        except Exception:
            await self.client.write_gatt_char(CHR_WRITE, frame, response=True)

    async def collect(self, wait: float = 1.2) -> list[bytes]:
        before = len(self.bufs)
        await asyncio.sleep(wait)
        return [b for _, b in self.bufs[before:]]


def show_frames(frames: list[bytes]) -> bool:
    got = False
    for data in frames:
        got = True
        parsed = packet.parse_frame(data)
        print(f"  ← {len(data):3d}B  {hexs(data)}")
        if parsed:
            cmd, payload = parsed
            print(f"       cmd=0x{cmd:02x} payload={len(payload)}B")
            for tag, val in decode_tlvs(payload):
                ascii_ = val.decode("ascii", "replace") if all(32 <= b < 127 for b in val) else ""
                extra = f"  ascii={ascii_!r}" if ascii_ else ""
                num = f" = {int.from_bytes(val, 'little')}" if len(val) <= 2 else ""
                print(f"       tag=0x{tag:02x} len={len(val)} {hexs(val)}{num}{extra}")
    if not got:
        print("  （无回包）")
    return got


async def cmd_info(args) -> int:
    async with Link(args.address) as link:
        print("发 cmd 0x01（读状态）…")
        await link.send(packet.build_frame(0x01))
        frames = await link.collect(args.wait)
        ok = show_frames(frames)
        if not ok:
            print("  提示：设备可能已被手机 App 或浏览器占着（同一时间只能一个连接）")
    return 0 if ok else 1


async def cmd_cmd(args) -> int:
    payload = bytes.fromhex(args.payload.replace(" ", "")) if args.payload else b""
    cmdi = int(args.cmd, 16)
    frame = packet.build_frame(cmdi, payload)
    print(f"发 cmd=0x{cmdi:02x} payload={len(payload)}B → {hexs(frame)}")
    async with Link(args.address) as link:
        await link.send(frame)
        show_frames(await link.collect(args.wait))
    return 0


async def cmd_sweep(args) -> int:
    """逐个命令试探（只发不带 payload 的空命令，避免改设备状态）"""
    print("逐个发空命令，看哪些有回包（只发无 payload 的，不会改配置）")
    async with Link(args.address) as link:
        for cmdi in range(0x01, 0x09):
            frame = packet.build_frame(cmdi)
            await link.send(frame)
            frames = await link.collect(args.wait)
            head = f"cmd=0x{cmdi:02x}"
            if frames:
                print(f"\n{head}  有回包 {len(frames)} 条")
                show_frames(frames)
            else:
                print(f"{head}  无回包")
            await asyncio.sleep(0.2)
    return 0


def main(argv=None) -> int:
    # 用 SUPPRESS 让 --timeout/--wait 写在子命令前后都生效（argparse 的默认值会覆盖父级已解析值）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--timeout", type=float, default=argparse.SUPPRESS, help="扫描时长")
    common.add_argument("--wait", type=float, default=argparse.SUPPRESS, help="每步等待回包时长")

    ap = argparse.ArgumentParser(parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", parents=[common])
    s.set_defaults(func=cmd_scan, needs_addr=False)
    for name, fn in (("gatt", cmd_gatt), ("info", cmd_info), ("sweep", cmd_sweep)):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("address")
        p.set_defaults(func=fn, needs_addr=True)
    p = sub.add_parser("cmd", parents=[common])
    p.add_argument("address")
    p.add_argument("cmd", help="十六进制命令字，例如 01")
    p.add_argument("payload", nargs="?", default="", help="十六进制 payload")
    p.set_defaults(func=cmd_cmd, needs_addr=True)

    args = ap.parse_args(argv)
    args.timeout = getattr(args, "timeout", None) or 8.0
    args.wait = getattr(args, "wait", None) or 1.2
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
