"""
memobird_printer.cli — 命令行入口

    python -m memobird_printer selftest                 # 无硬件自检（帧算法/位图/BMP）
    python -m memobird_printer preview "文本" -o p.png   # 本地看抖动效果
    python -m memobird_printer scan                      # 扫蓝牙打印机
    python -m memobird_printer gatt AA:BB:CC:DD:EE:FF    # 打印 GATT 表（找特征值）
    python -m memobird_printer lan-scan                  # 扫局域网打印机
    python -m memobird_printer status  --lan 192.168.1.5
    python -m memobird_printer text    "hello" --lan 192.168.1.5
    python -m memobird_printer text    "hello" --ble AA:BB:CC:DD:EE:FF
    python -m memobird_printer text    "hello" --spp COM5
    python -m memobird_printer image   pic.png --lan 192.168.1.5
    python -m memobird_printer image   pic.png --ble AA:BB:CC:DD:EE:FF --mode atkinson
    python -m memobird_printer cloud-bind  --ak XXX --device 9d15e1b2671043ee --ident me
    python -m memobird_printer cloud-text  "hi" --ak XXX --device ... --userid 123
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import packet
from .image import PRINTER_WIDTH, dither_to_raw, prepare, preview, raw_to_bmp


# --------------------------------------------------------------------------- #
def _target(args) -> str:
    if args.lan:
        return "lan"
    if args.ble:
        return "ble"
    if args.spp:
        return "spp"
    return "lan"


def _make_image(args):
    if args.image:
        from PIL import Image

        src = Image.open(args.image)
    else:
        src = args.text or ""
    img = prepare(src, mode=args.mode, font_size=args.font_size, font=args.font, invert=args.invert)
    return dither_to_raw(img, args.mode)


# --------------------------------------------------------------------------- #
def cmd_selftest(args) -> int:
    ok = True

    vectors = [
        ("LED 开", packet.build_frame(packet.CMD_CONTROL, packet.tlv(0x03, b"\x01")), "aa0500030301000149"),
        ("读状态", packet.build_frame(packet.CMD_STATUS), "aa01000154"),
        ("打印头 3 个 TLV",
         packet.build_frame(packet.CMD_PRINT,
                            packet.tlv(0x0B, b"\x05\x00") + packet.tlv(0x0C, b"\x01\x00") + packet.tlv(0x0A, b"\x29\x00")),
         "aa1000040b020005000c020001000a02002900ec"),
    ]
    print("== 帧算法自检（与文档实测报文逐字节比对）==")
    for name, got, want in vectors:
        good = got.hex() == want
        ok &= good
        print(f"  [{'OK ' if good else 'FAIL'}] {name:<14} {got.hex()}")
        if not good:
            print(f"         expect {want}")

    print("\n== 位图 / BMP 自检 ==")
    img = prepare("咕咕机 selftest 0123", mode="floyd")
    w, h, raw = dither_to_raw(img, "floyd")
    print(f"  渲染: {w}x{h}px (期望宽度 {PRINTER_WIDTH})  raw={len(raw)}B 行字节={(w + 7) // 8}")
    ok &= w == PRINTER_WIDTH
    bmp = raw_to_bmp(w, h, raw, top_down=True)
    good = bmp[:2] == b"BM" and len(bmp) > 54 + len(raw) // 2
    ok &= good
    import struct
    bi_height = struct.unpack("<i", bmp[22:26])[0] if len(bmp) > 26 else 0
    print(f"  BMP: {len(bmp)}B magic={bmp[:2]!r} biHeight={bi_height} (负数=top-down，符合要求)")
    ok &= bi_height == -h

    job = packet.build_bitmap_job(raw)
    print(f"  蓝牙分帧: {job.chunks} 帧, 总长 {job.total_bytes}B, 首帧 {len(job.frames[0])}B")
    good = all(len(f) <= 1100 for f in job.frames)
    ok &= good
    print(f"  每帧 <=1100B: {good}")

    print("\n== 依赖 ==")
    for mod, hint in (("PIL", "pip install pillow"), ("requests", "pip install requests"),
                      ("bleak", "pip install bleak (蓝牙需要)"), ("serial", "pip install pyserial (SPP 需要)")):
        try:
            __import__(mod)
            print(f"  [OK ] {mod}")
        except ImportError:
            print(f"  [ -- ] {mod} 未安装：{hint}")

    print("\n结果:", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


def cmd_preview(args) -> int:
    out = args.out or "preview.png"
    if args.image:
        from PIL import Image

        img = prepare(Image.open(args.image), mode=args.mode)
    else:
        img = prepare(args.text or "", mode=args.mode, font_size=args.font_size, font=args.font, invert=args.invert)
    preview(img, out, args.mode, scale=args.scale)
    print(f"已生成 {out}")
    return 0


def cmd_scan(args) -> int:
    from .ble import scan

    rows = asyncio.run(scan(args.timeout, all_devices=args.all))
    if not rows:
        print("没扫到候选设备；加 --all 看全部蓝牙设备")
        return 1
    for r in rows:
        print(f"  {r['address']}  rssi={r['rssi']}  {r['name']}  {r['uuids'] or ''}")
    return 0


def cmd_gatt(args) -> int:
    from .ble import gatt_dump

    for row in asyncio.run(gatt_dump(args.address)):
        if row["type"] == "service":
            print(f"service {row['uuid']}")
        else:
            props = ",".join(row["props"])
            mark = "  <-- 可写" if any(p in ("write", "write-without-response") for p in row["props"]) else ""
            print(f"    chr {row['uuid']}  handle={row['handle']}  [{props}]{mark}")
    return 0


def cmd_lan_scan(args) -> int:
    from .lan import discover

    hosts = discover(args.subnet, timeout=0.35)
    print("\n".join(hosts) if hosts else "没找到（打印机可能不在同一网段 / 不是 WiFi 机型）")
    return 0 if hosts else 1


def cmd_status(args) -> int:
    if args.lan:
        from .lan import LanPrinter

        print(json.dumps(LanPrinter(args.lan).status(), ensure_ascii=False, indent=2))
        return 0
    if args.ble:
        async def run():
            from .ble import BlePrinter

            async with BlePrinter(args.ble) as b:
                await b.status()
        asyncio.run(run())
        return 0
    print("需要 --lan 或 --ble")
    return 1


def cmd_print(args) -> int:
    w, h, raw = _make_image(args)
    bmp = raw_to_bmp(w, h, raw, top_down=True)
    print(f"图像 {w}x{h}px  raw={len(raw)}B  bmp={len(bmp)}B")

    if args.lan:
        from .lan import LanPrinter

        p = LanPrinter(args.lan)
        if args.text or (not args.image):
            print(json.dumps(p.print_text(args.text or ""), ensure_ascii=False))
        else:
            print(json.dumps(p.print_image(bmp), ensure_ascii=False))
        return 0

    if args.ble:
        async def run():
            from .ble import BlePrinter

            async with BlePrinter(args.ble) as b:
                if args.text and not args.image:
                    await b.print_text(args.text)
                else:
                    await b.print_raw_image(raw)
        asyncio.run(run())
        print("已发送")
        return 0

    if args.spp:
        from .ble import SppPrinter

        with SppPrinter(args.spp) as p:
            if args.text and not args.image:
                p.print_text(args.text)
            else:
                p.print_raw_image(raw)
        print("已发送")
        return 0

    print("需要 --lan / --ble / --spp 之一")
    return 1


def cmd_cloud_bind(args) -> int:
    from .cloud import CloudPrinter

    p = CloudPrinter(args.ak, args.device)
    print(json.dumps(p.bind(args.ident), ensure_ascii=False, indent=2))
    return 0


def cmd_cloud_text(args) -> int:
    from .cloud import CloudPrinter

    p = CloudPrinter(args.ak, args.device, args.userid)
    print(json.dumps(p.print_text(args.text), ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="memobird_printer", description="咕咕机 / 有道口袋打印机 通用 Python 控制")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("selftest", help="无硬件自检")
    s.set_defaults(func=cmd_selftest)

    for name, fn in (("preview", cmd_preview), ("text", cmd_print), ("image", cmd_print), ("status", cmd_status)):
        p = sub.add_parser(name)
        p.add_argument("text", nargs="?", help="要打印的文本")
        p.add_argument("-i", "--image", help="图片路径")
        p.add_argument("-o", "--out", help="预览输出 png")
        p.add_argument("--lan", help="局域网打印机 IP")
        p.add_argument("--ble", help="BLE 设备地址")
        p.add_argument("--spp", help="串口 COM 名")
        p.add_argument("--mode", default="floyd", choices=["none", "floyd", "atkinson", "bayer", "threshold"])
        p.add_argument("--font", help="字体文件")
        p.add_argument("--font-size", type=int, default=24)
        p.add_argument("--scale", type=int, default=2)
        p.add_argument("--invert", action="store_true")
        p.set_defaults(func=fn)

    s = sub.add_parser("scan")
    s.add_argument("--timeout", type=float, default=8)
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("gatt")
    s.add_argument("address")
    s.set_defaults(func=cmd_gatt)

    s = sub.add_parser("lan-scan")
    s.add_argument("--subnet", help="例如 192.168.1")
    s.set_defaults(func=cmd_lan_scan)

    s = sub.add_parser("cloud-bind")
    s.add_argument("--ak", required=True)
    s.add_argument("--device", required=True)
    s.add_argument("--ident", required=True)
    s.set_defaults(func=cmd_cloud_bind)

    s = sub.add_parser("cloud-text")
    s.add_argument("text")
    s.add_argument("--ak", required=True)
    s.add_argument("--device", required=True)
    s.add_argument("--userid", type=int, required=True)
    s.set_defaults(func=cmd_cloud_text)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
