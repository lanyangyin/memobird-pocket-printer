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
        src = getattr(args, "text", None) or ""
    img = prepare(src, mode=args.mode, font_size=args.font_size, font=args.font, invert=args.invert)

    # 整张纸正好 N 毫米：给内容补白（或裁切）到目标高度
    total_mm = getattr(args, "total_mm", None)
    target_mm = getattr(args, "length_mm", None)
    if total_mm or target_mm:
        from .paper import OVERHEAD_MM, pad_to_length

        before = img.size[1]
        if total_mm:
            img = pad_to_length(img, float(total_mm), align=getattr(args, "align", "top"), total=True)
            print(f"纸总长 {total_mm}mm：内容 {before} 点 → {img.size[1]} 点"
                  f"（{img.size[1] / 8:.1f}mm + 固件 {OVERHEAD_MM:.0f}mm）")
        else:
            img = pad_to_length(img, float(target_mm), align=getattr(args, "align", "top"))
            print(f"内容高度：{before} 点 → {img.size[1]} 点（{target_mm}mm @203dpi）")

    args._gray = img
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
            from .paper import FAST_PATH_FRAMES, MAX_ROWS_PER_JOB, paginate

            async with BlePrinter(args.ble, chunk=getattr(args, "chunk", 180),
                                  settle=getattr(args, "settle", 0.002),
                                  batch=getattr(args, "batch", 1),
                                  window=getattr(args, "window", 1)) as b:
              dens = getattr(args, "density", 0) or 0
              restore = None
              try:
                preheat = not getattr(args, "no_preheat", False)

                # 降浓度 = 每行加热更久 = 打印变慢 → 慢速 BLE 下长图才打得完整
                if dens:
                    from . import device as _dev
                    infos = await _dev.read_info(b, detail=False, wait=1.2)
                    restore = infos[-1].value(0x02) if infos else _dev.DEFAULT_DENSITY
                    if restore == dens:
                        print(f"浓度：已是 {dens}，跳过设置")
                        restore = None
                    else:
                        await b.transact(packet.build_frame(packet.CMD_CONTROL,
                                                            packet.tlv(0x02, bytes([dens]))),
                                         wait=0.4, retries=1)
                        print(f"浓度：{restore} → {dens}（打完恢复）")

                text_arg = getattr(args, "text", None)
                is_text = bool(text_arg) and not _image_path(args)
                plain_ascii = bool(text_arg) and all(ord(c) < 128 for c in text_arg)

                if is_text and plain_ascii:
                    # 纯 ASCII：走固件文本帧（体积最小、最快）
                    job = packet.job_for_text(text_arg)
                    await b.send_frames(job.frames, preheat=preheat, inter_frame=0.03)
                else:
                    if is_text:
                        # 中文必须走位图：这台固件的 GBK 文本帧没有中文字形（打出来是黑块）
                        print("文本含中文 → 改走位图（GBK 文本帧无中文字形）", file=sys.stderr)

                    threshold = (getattr(args, "paginate_rows", None)
                                 or MAX_ROWS_PER_JOB)
                    pages = ([args._gray] if getattr(args, "no_paginate", False)
                             else paginate(args._gray, threshold))
                    if len(pages) > 1:
                        print(f"图高 {args._gray.size[1]} 行超过单任务阈值 "
                              f"→ 分 {len(pages)} 页（页间有固件 18mm 空隙）", file=sys.stderr)

                    for n, page in enumerate(pages, 1):
                        pw, ph, praw = dither_to_raw(page, args.mode)
                        pjob = packet.build_bmp_job(
                            raw_to_bmp(pw, ph, praw, official=True),
                            chunk=getattr(args, "bmp_chunk", 1024))

                        # 自动选节奏：短内容不等 ack（连续、不顿）；长内容必须流控（否则丢数据）
                        use_flow = len(pjob.frames) > FAST_PATH_FRAMES and not getattr(args, "no_flow", False)
                        print(f"  {len(pjob.frames)} 帧 → "
                              f"{'流控（完整但会顿）' if use_flow else '快速路径（连续）'}",
                              file=sys.stderr)

                        await b.send_frames(pjob.frames, preheat=preheat,
                                            inter_frame=getattr(args, "inter_frame", 0.03),
                                            wait_ack=use_flow, flow_control=use_flow)
                        if len(pages) > 1:
                            print(f"  第 {n}/{len(pages)} 页  {ph} 行 ({ph / 8:.1f}mm)", file=sys.stderr)
                            await asyncio.sleep(0.3)
                            await b.transact(packet.commit_frame(), wait=0.6, retries=1)

                    # 终结帧：让固件把位图真正打出来（不驱动电机 ⇒ 不多走纸）
                    term = getattr(args, "terminator", "commit")
                    if term == "feed":
                        await asyncio.sleep(0.3)
                        await b.send_frames(packet.feed_job(3).frames, preheat=False, inter_frame=0.03)
                    else:
                        await asyncio.sleep(0.2)
                        await b.transact(packet.commit_frame(), wait=0.6, retries=1)


              finally:
                # 无论成功失败，都尽量把浓度恢复回去
                if dens and restore is not None:
                    try:
                        await asyncio.sleep(0.2)
                        if not b.is_connected:
                            # 打印结束后固件会主动断开，恢复浓度前先重连
                            await b.reconnect()
                        await b.transact(packet.build_frame(packet.CMD_CONTROL,
                                                            packet.tlv(0x02, bytes([int(restore)]))),
                                         wait=0.4, retries=2)
                        print(f"浓度已恢复为 {restore}")
                    except Exception as exc:                        # noqa: BLE001
                        print(f"⚠ 浓度恢复失败（{type(exc).__name__}），设备当前浓度可能不是 {restore}",
                              file=sys.stderr)

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
        from .paper import OVERHEAD_MM

        if mm < OVERHEAD_MM:
            print(f"⚠ 最小出纸约 {OVERHEAD_MM:.0f}mm（固件固定开销），已按最小值处理",
                  file=sys.stderr)
        frames, meta = blank_frames(mm=mm, dpi=args.dpi, tick=args.tick,
                                    total=not getattr(args, "content", False))
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
# --------------------------------------------------------------------------- #
# 底层操作（把能实现的能力全部暴露出来）
# --------------------------------------------------------------------------- #
def _ble_of(args):
    addr = getattr(args, "ble", None)
    if not addr:
        print("需要 --ble <地址>", file=sys.stderr)
        return None
    return addr


def cmd_raw(args) -> int:
    """发任意十六进制帧（原样写到 ff02），打印回包"""
    addr = _ble_of(args)
    if not addr:
        return 1
    from .ble import BlePrinter

    async def run():
        async with BlePrinter(addr, chunk=args.chunk, settle=args.settle, echo=False) as b:
            frames = await b.send_hex(args.hex)
            for f in frames:
                print(f"  ← {f.hex(' ')}")
            if not frames:
                print("  （无回包）")
    asyncio.run(run())
    return 0


def cmd_cmd(args) -> int:
    """构造并发送一条命令：cmd + 若干 TLV（tag/len/value）"""
    addr = _ble_of(args)
    if not addr:
        return 1
    from .ble import BlePrinter

    payload = b""
    for spec in args.tlv or []:
        # 格式 tag:值（单字节）或 tag:hex:0102
        parts = spec.split(":")
        tag = int(parts[0], 0)
        if len(parts) == 3 and parts[1] == "hex":
            val = bytes.fromhex(parts[2])
        else:
            val = bytes([int(parts[1], 0)]) if len(parts) > 1 else b"\x01"
        payload += packet.tlv(tag, val)

    frame = packet.build_frame(int(args.cmd, 0), payload)
    print(f"发送: {frame.hex(' ')}")

    async def run():
        async with BlePrinter(addr, chunk=args.chunk, settle=args.settle, echo=False) as b:
            frames = await b.transact(frame, wait=args.wait, retries=1)
            for f in frames:
                print(f"  ← {f.hex(' ')}")
            if not frames:
                print("  （无回包）")
    asyncio.run(run())
    return 0


def cmd_notify(args) -> int:
    """只订阅通知，监听 N 秒（看看设备主动推什么）"""
    addr = _ble_of(args)
    if not addr:
        return 1
    from .ble import BlePrinter

    async def run():
        async with BlePrinter(addr, chunk=args.chunk, settle=args.settle, echo=False) as b:
            print(f"监听 {args.seconds} 秒…")
            frames = await b.watch(args.seconds)
            for f in frames:
                print(f"  ← {f.hex(' ')}")
            print(f"共 {len(frames)} 帧")
    asyncio.run(run())
    return 0


def cmd_gatt_read(args) -> int:
    """读任意 GATT 特征值"""
    addr = _ble_of(args)
    if not addr:
        return 1
    from .ble import BlePrinter

    async def run():
        async with BlePrinter(addr, echo=False) as b:
            if args.list:
                for line in await b.list_gatt():
                    print(line)
                return
            data = await b.read_char(args.uuid)
            print(f"{args.uuid}: {data.hex(' ')}")
            try:
                print(f"  ascii: {data.decode('utf-8')}")
            except Exception:
                pass
    asyncio.run(run())
    return 0


def cmd_gatt_write(args) -> int:
    """写任意 GATT 特征值（十六进制）"""
    addr = _ble_of(args)
    if not addr:
        return 1
    from .ble import BlePrinter

    data = bytes.fromhex(args.hex.replace(" ", ""))

    async def run():
        async with BlePrinter(addr, echo=False) as b:
            await b.write_hex(args.uuid, data)
            print(f"已写入 {args.uuid}: {data.hex(' ')}")
    asyncio.run(run())
    return 0


def build_parser() -> argparse.ArgumentParser:
    from . import __version__

    ap = argparse.ArgumentParser(prog="memobird_printer", description="咕咕机 / 有道口袋打印机 通用 Python 控制")
    ap.add_argument("--version", action="version", version=f"memobird_printer {__version__}")
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
        p.add_argument("--length-mm", type=float,
                       help="内容高度补白/裁切到 N 毫米（不含固件固定的 18mm）")
        p.add_argument("--total-mm", type=float,
                       help="纸总长正好 N 毫米（自动扣掉固件固定多喂的 18mm）")
        p.add_argument("--align", default="top", choices=["top", "center", "bottom"],
                       help="补白时内容放哪（默认 top）")
        p.add_argument("--no-preheat", action="store_true", help="不发热身包（排查用）")
        p.add_argument("--chunk", type=int, default=180, help="GATT 每次写入字节数")
        p.add_argument("--settle", type=float, default=0.002, help="每片之后停顿（秒）")
        # ---- 底层参数（默认值适合绝大多数场景，需要时再调）----
        p.add_argument("--batch", type=int, default=1, help="并发写入数（>1 提速，可能丢包）")
        p.add_argument("--window", type=int, default=1,
                       help="流控窗口（1=逐帧等 ack，最稳；>1 可能丢数据）")
        p.add_argument("--bmp-chunk", type=int, default=1024,
                       help="位图每帧载荷字节（固件只收 <=1024）")
        p.add_argument("--no-paginate", action="store_true", help="不分页，整张一次发")
        p.add_argument("--paginate-rows", type=int, default=None,
                       help="分页阈值（默认用 paper.MAX_ROWS_PER_JOB）")
        p.add_argument("--density", type=int, default=10,
                       help="打印浓度 1..10（默认 10，最深；传 0 = 不动设备当前值）")
        p.add_argument("--no-flow", action="store_true", help="关闭逐帧流控（排查用）")
        p.add_argument("--inter-frame", type=float, default=0.03,
                       help="帧间固定间隔（秒）；0.2~0.4 可让出纸连续又不丢数据")
        p.add_argument("--terminator", default="commit", choices=["commit", "feed"],
                       help="收尾方式：commit=提交帧(默认) / feed=再走 N 行空白")
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

    s = sub.add_parser("raw", help="发任意十六进制帧")
    s.add_argument("hex", help="例如 aa01000154")
    s.add_argument("--ble", required=True)
    s.add_argument("--chunk", type=int, default=180)
    s.add_argument("--settle", type=float, default=0.002)
    s.set_defaults(func=cmd_raw)

    s = sub.add_parser("cmd", help="构造并发送命令（cmd + TLV）")
    s.add_argument("cmd", help="命令码，如 0x08")
    s.add_argument("--tlv", action="append", metavar="TAG:VAL",
                   help="TLV，可多次；TAG:VAL 或 TAG:hex:0102")
    s.add_argument("--ble", required=True)
    s.add_argument("--wait", type=float, default=1.0)
    s.add_argument("--chunk", type=int, default=180)
    s.add_argument("--settle", type=float, default=0.002)
    s.set_defaults(func=cmd_cmd)

    s = sub.add_parser("notify", help="只监听设备通知 N 秒")
    s.add_argument("--ble", required=True)
    s.add_argument("--seconds", type=float, default=10)
    s.add_argument("--chunk", type=int, default=180)
    s.add_argument("--settle", type=float, default=0.002)
    s.set_defaults(func=cmd_notify)

    s = sub.add_parser("gatt-read", help="读任意 GATT 特征值（--list 列出全部）")
    s.add_argument("--ble", required=True)
    s.add_argument("--uuid", default="00002a29-0000-1000-8000-00805f9b34fb")
    s.add_argument("--list", action="store_true", help="列出所有服务/特征值")
    s.set_defaults(func=cmd_gatt_read)

    s = sub.add_parser("gatt-write", help="写任意 GATT 特征值（十六进制）")
    s.add_argument("--ble", required=True)
    s.add_argument("--uuid", required=True)
    s.add_argument("--hex", required=True)
    s.set_defaults(func=cmd_gatt_write)

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
    s.add_argument("--content", action="store_true",
                   help="--mm 表示内容长度（默认是纸总长；内容长度 = 总长 + 18mm）")
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
