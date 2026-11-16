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

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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


def _image_path(args) -> str | None:
    """兼容 `image a.png` 与 `image -i a.png` 两种写法"""
    return args.image or getattr(args, "image_pos", None)


def _make_image(args):
    if _image_path(args):
        from PIL import Image

        src = Image.open(_image_path(args))
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

    import struct
    # 官方格式：biHeight 为正，但行序 top-down（GT1 固件就吃这个）
    bmp = raw_to_bmp(w, h, raw, official=True)
    bi_height = struct.unpack("<i", bmp[22:26])[0] if len(bmp) > 26 else 0
    good = bmp[:2] == b"BM" and bi_height == h
    ok &= good
    print(f"  BMP(official): {len(bmp)}B magic={bmp[:2]!r} biHeight={bi_height} (+{h} = 官方格式)")

    # 规范格式（负高度）保留给局域网/云端等可能要求规范的场景
    bmp2 = raw_to_bmp(w, h, raw, top_down=True, official=False)
    bi2 = struct.unpack("<i", bmp2[22:26])[0] if len(bmp2) > 26 else 0
    ok &= bi2 == -h
    print(f"  BMP(规范):     {len(bmp2)}B biHeight={bi2} (-{h} = top-down 规范写法)")

    job = packet.build_bmp_job(bmp)
    print(f"  蓝牙分帧: {job.chunks} 帧, 总长 {job.total_bytes}B, 首帧 {len(job.frames[0])}B")
    good = all(len(f) <= 1100 for f in job.frames)
    ok &= good
    print(f"  每帧 <=1100B: {good}")

    tj = packet.job_for_text("字号档位测试", bold=True, underline=False, font_size=2)
    print(f"  文本帧: {tj.chunks} 帧, 带 0x0D(加粗)/0x11(下划线)/0x10(字号档位)")
    ok &= tj.chunks >= 1

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
    if _image_path(args):
        from PIL import Image

        img = prepare(Image.open(_image_path(args)), mode=args.mode)
    else:
        img = prepare(getattr(args, "text", None) or "", mode=args.mode, font_size=args.font_size, font=args.font, invert=args.invert)
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
        if getattr(args, "text", None) or (not _image_path(args)):
            print(json.dumps(p.print_text(getattr(args, "text", None) or ""), ensure_ascii=False))
        else:
            print(json.dumps(p.print_image(bmp), ensure_ascii=False))
        return 0

    if args.ble:
        async def run():
            from .ble import BlePrinter

            async with BlePrinter(args.ble) as b:
                if getattr(args, "text", None) and not _image_path(args):
                    await b.print_text(getattr(args, "text", None) or "")
                else:
                    await b.print_raw_image(raw)
        asyncio.run(run())
        print("已发送")
        return 0

    if args.spp:
        from .ble import SppPrinter

        with SppPrinter(args.spp) as p:
            if getattr(args, "text", None) and not _image_path(args):
                p.print_text(getattr(args, "text", None) or "")
            else:
                p.print_raw_image(raw)
        print("已发送")
        return 0

    print("需要 --lan / --ble / --spp 之一")
    return 1


def cmd_feed(args) -> int:
    """走纸：--mm 精确（白图按点数）或 --lines 粗（换行）"""
    from .paper import blank_frames, line_frames

    if args.text:
        # 兼容 `feed 50` 这种写法：位置参数当毫米
        mm = float(args.text)
    elif args.mm is not None:
        mm = float(args.mm)
    else:
        mm = None

    if mm is not None:
        frames, meta = blank_frames(mm=mm, dpi=args.dpi, tick=args.tick)
    else:
        frames, meta = line_frames(args.lines)

    print(f"走纸 {meta['mm'] if 'mm' in meta else str(meta['lines']) + ' 行'}："
          f"{len(frames)} 帧 / {meta['bytes']}B")

    if args.lan:
        print("局域网机型不支持白图走纸（会打出一张空白纸）", file=sys.stderr)
        return 1
    if args.ble:
        from .ble import BlePrinter

        async def run():
            async with BlePrinter(args.ble, echo=False) as b:
                await b.send_frames(frames, preheat=True, inter_frame=0.01)
        asyncio.run(run())
        print("已发送")
        return 0
    if args.spp:
        from .ble import SppPrinter

        with SppPrinter(args.spp) as p:
            p.send_frames(frames, preheat=True)
        print("已发送")
        return 0
    print("需要 --ble / --spp 之一", file=sys.stderr)
    return 1


def cmd_info(args) -> int:
    """读设备信息（cmd 0x01）：电量/序列号/各状态字"""
    if not args.ble:
        print("需要 --ble <地址>", file=sys.stderr)
        return 1
    from .ble import BlePrinter
    from . import device

    async def run():
        async with BlePrinter(args.ble, echo=False) as b:
            return await b.read_device_info(wait=args.wait)

    infos, frames = asyncio.run(run())
    if not frames:
        print("设备没有回包（可能被别的 App/浏览器占着，或者固件不支持）", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([i.as_dict() for i in infos], ensure_ascii=False, indent=2))
    else:
        for line in device.decode_text(frames):
            print(line)
    return 0


def cmd_sweep(args) -> int:
    """逐个命令试探：只发无 payload 的空命令，不会改配置"""
    if not args.ble:
        print("需要 --ble <地址>", file=sys.stderr)
        return 1
    from .ble import BlePrinter

    cmds = list(range(args.start, args.end + 1))

    async def run():
        async with BlePrinter(args.ble, echo=False) as b:
            return await b.sweep(cmds, wait=args.wait)

    out = asyncio.run(run())
    for cmdi, frames in out.items():
        if frames:
            print(f"cmd=0x{cmdi:02x}  回包 {len(frames)} 条:")
            for f in frames:
                print(f"  {f.hex(' ')}")
        else:
            print(f"cmd=0x{cmdi:02x}  无回包")
    return 0


def cmd_setting(args) -> int:
    """写一个已验证的设置项（tag 0x02 时间 / 0x03 指示灯），写完读回状态"""
    if not args.ble:
        print("需要 --ble <地址>", file=sys.stderr)
        return 1
    from .ble import BlePrinter
    from . import device

    tag = int(args.tag, 0)
    value = int(args.value, 0)
    try:
        frame = device.setting_frame(tag, value)          # 先做参数校验
    except ValueError as exc:
        print(f"参数不合法：{exc}", file=sys.stderr)
        return 1

    async def run():
        async with BlePrinter(args.ble, echo=False) as b:
            await b.transact(frame, wait=1.0)
            return await device.read_info(b, detail=False, wait=1.5)

    infos = asyncio.run(run())
    if not infos:
        print("命令已发出，但没读到状态回包", file=sys.stderr)
        return 1
    info = infos[-1]
    print(f"写入 0x{tag:02x} = {value}")
    for line in device.decode_text([info.raw]):
        print(line)
    got = info.value(tag)
    print(f"\n读回 0x{tag:02x} = {got}  {'✅ 生效' if got == value else '⚠️ 与写入值不一致'}")
    return 0


def cmd_cloud_bind(args) -> int:
    from .cloud import CloudPrinter

    p = CloudPrinter(args.ak, args.device)
    print(json.dumps(p.bind(args.ident), ensure_ascii=False, indent=2))
    return 0


def cmd_cloud_text(args) -> int:
    from .cloud import CloudPrinter

    p = CloudPrinter(args.ak, args.device, args.userid)
    print(json.dumps(p.print_text(getattr(args, "text", None) or ""), ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="memobird_printer", description="咕咕机 / 有道口袋打印机 通用 Python 控制")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("selftest", help="无硬件自检")
    s.set_defaults(func=cmd_selftest)

    def _common(p):
        p.add_argument("-i", "--image", help="图片路径")
        p.add_argument("-o", "--out", help="预览输出 png")
        p.add_argument("--lan", help="局域网打印机 IP")
        p.add_argument("--ble", help="BLE 设备地址")
        p.add_argument("--spp", help="串口 COM 名")
        p.add_argument("--mode", default="floyd",
                       choices=["none", "floyd", "atkinson", "bayer", "threshold"])
        p.add_argument("--font", help="字体文件")
        p.add_argument("--font-size", type=int, default=24)
        p.add_argument("--scale", type=int, default=2)
        p.add_argument("--invert", action="store_true")
        return p

    # preview / text：位置参数是文本
    for name, fn in (("preview", cmd_preview), ("text", cmd_print)):
        p = _common(sub.add_parser(name))
        p.add_argument("text", nargs="?", help="要打印的文本")
        p.set_defaults(func=fn)

    # image：位置参数是图片路径（也可以 -i 指定）
    p = _common(sub.add_parser("image"))
    p.add_argument("image_pos", nargs="?", help="图片路径")
    p.set_defaults(func=cmd_print)

    # status：只要目标
    p = _common(sub.add_parser("status"))
    p.set_defaults(func=cmd_status)

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

    s = sub.add_parser("feed", help="走纸：--mm 精确（白图点数）/ --lines 粗（换行）")
    s.add_argument("text", nargs="?", help="毫米数（位置写法，如 feed 50）")
    s.add_argument("--mm", type=float, help="走纸长度（毫米）")
    s.add_argument("--lines", type=int, default=3, help="按行走纸（粗）")
    s.add_argument("--dpi", type=int, default=203, choices=[203, 300])
    s.add_argument("--tick", action="store_true", help="画 1 个黑点，防止固件跳过全白图")
    s.add_argument("--ble")
    s.add_argument("--spp")
    s.add_argument("--lan")
    s.set_defaults(func=cmd_feed)

    s = sub.add_parser("info", help="读设备信息（序列号/状态字，cmd 0x01）")
    s.add_argument("--ble", required=True)
    s.add_argument("--wait", type=float, default=1.5, help="等回包时长")
    s.add_argument("--json", action="store_true", help="输出 JSON")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("sweep", help="逐个命令试探（只发空命令，不改配置）")
    s.add_argument("--ble", required=True)
    s.add_argument("--start", type=lambda v: int(v, 0), default=1)
    s.add_argument("--end", type=lambda v: int(v, 0), default=8)
    s.add_argument("--wait", type=float, default=0.8)
    s.set_defaults(func=cmd_sweep)

    s = sub.add_parser("setting", help="写设置项（0x02 时间 / 0x03 指示灯）并读回")
    s.add_argument("--ble", required=True)
    s.add_argument("--tag", required=True, help="如 0x02")
    s.add_argument("--value", required=True, help="如 5")
    s.set_defaults(func=cmd_setting)

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
