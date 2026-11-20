"""WeiDa-Label / Dothantech 标签机协议 —— 参考实现（无需厂商 App）

覆盖：
* 帧封装（AA/BB + 变长长度 + 校验），cmd=0 时原样透传（ESC/POS 字节流就走这条）
* ESC/POS 光栅图（GS v 0）与走纸（ESC J）
* 解析设备回包

用法：
    python weida_protocol.py demo            # 打一张测试图的字节流（hex 打印，不连设备）
    python weida_protocol.py frame 40 4101 02  --crc   # 手工构造一帧

来源：jadx 反编译 com.dothantech.data.b / BitmapPackage / printer.a
"""
from __future__ import annotations

import argparse
import sys

# --------------------------------------------------------------------------- #
# 帧常量（com.dothantech.data.b）
# --------------------------------------------------------------------------- #
START_HOST_TO_PRINTER = 0xAA     # 新模式；老固件是 0x1F
START_PRINTER_TO_HOST = 0xBB     # 新模式；老固件是 0x1F
NO_CRC_MARK = 0x88               # CRC 位置填 0x88 表示不校验

CMD_RAW = 0x00                   # cmd==0：不加帧头/长度/校验，原样发送 payload
CMD_PROBE = 0x79                 # 能力探测示例
CMD_RASTER_LEGACY = 0x2B         # 老机型光栅命令：'(' 2B）＋两个变长参数
CMD_GS_RASTER = b"\x1d\x76\x30"  # GS v 0 —— 标准 ESC/POS 光栅
CMD_ESC_FEED = 0x4A              # ESC J n —— 走纸 n 点


# --------------------------------------------------------------------------- #
# 变长整数 / 校验
# --------------------------------------------------------------------------- #
def encode_len(n: int) -> bytes:
    """长度编码：<192 单字节；否则 (0xC0|hi, lo)。"""
    if n < 0:
        raise ValueError("长度不能为负")
    if n < 192:
        return bytes([n])
    if n > 0x3FFF:
        raise ValueError("长度超过 0x3FFF，需要分包")
    return bytes([0xC0 | (n >> 8), n & 0xFF])


def encode_short(n: int) -> bytes:
    """参数里的"短整数"编码（b.j）：<192 一字节，否则 0xC0|hi, lo。"""
    return encode_len(n)


def checksum(cmd: int, payload: bytes) -> int:
    """CRC = ~(cmd + payload 各字节和) 的低 8 位。

    校验：cmd + sum(payload) + crc == 0xFF (mod 256)
    （即"含 CRC 的整段求和取反为 0"）
    """
    total = (cmd + sum(payload)) & 0xFF
    return (~total) & 0xFF


# --------------------------------------------------------------------------- #
# 组帧
# --------------------------------------------------------------------------- #
def frame(cmd: int, payload: bytes = b"", *, no_crc: bool = False) -> bytes:
    """构造一帧主机→打印机的命令。cmd==0 时返回原始 payload。"""
    if cmd == 0:
        return bytes(payload)
    out = bytearray()
    out.append(START_HOST_TO_PRINTER)
    out.append(cmd & 0xFF)
    out += encode_len(len(payload))
    out += payload
    out.append(NO_CRC_MARK if no_crc else checksum(cmd, payload))
    return bytes(out)


def frame_raw(data: bytes) -> bytes:
    """把一段原始字节（ESC/POS 指令）包成 cmd=0 透传包。"""
    return frame(CMD_RAW, data)


# --------------------------------------------------------------------------- #
# ESC/POS 打印指令（BitmapPackage 里的实现）
# --------------------------------------------------------------------------- #
def esc_feed(dots: int) -> bytes:
    """ESC J n —— 走纸 n 点（单次上限 255，超出自动拆）。"""
    out = bytearray()
    while dots >= 255:
        out += bytes([0x1B, CMD_ESC_FEED, 255])
        dots -= 255
    if dots > 0:
        out += bytes([0x1B, CMD_ESC_FEED, dots])
    return bytes(out)


def gs_raster(row_bytes: bytes, width_dots: int, height_dots: int) -> bytes:
    """GS v 0 m xL xH yL yH data —— ESC/POS 光栅位图（m=0 普通模式）。"""
    x = (width_dots + 7) // 8
    if len(row_bytes) != x * height_dots:
        raise ValueError(f"数据长度不对：期望 {x * height_dots}，实际 {len(row_bytes)}")
    out = bytearray(CMD_GS_RASTER)
    out.append(0)                      # m = 0
    out += bytes([x & 0xFF, (x >> 8) & 0xFF])
    out += bytes([height_dots & 0xFF, (height_dots >> 8) & 0xFF])
    out += row_bytes
    return bytes(out)


def raster_legacy(chunk: bytes, width_bytes: int) -> bytes:
    """老机型：cmd 0x2B + [行数-1, 每行字节数] + 数据。"""
    rows = len(chunk) // width_bytes if width_bytes else 0
    payload = encode_short(max(0, rows - 1)) + encode_short(width_bytes) + chunk
    return frame(CMD_RASTER_LEGACY, payload)


def job_from_1bpp(raw: bytes, width_dots: int, height_dots: int,
                  *, line_dots: int = 0, use_legacy: bool = False) -> bytes:
    """把 1bpp 位图（1=黑，行首对齐）打成完整打印字节流。"""
    row_bytes = (width_dots + 7) // 8
    if len(raw) < row_bytes * height_dots:
        raise ValueError("raw 长度不足")
    out = bytearray()
    # 老机型一般要先定位/清缓存；新机型直接 GS v 0 即可（见文档"待确认"一节）
    if use_legacy:
        out += raster_legacy(raw[: row_bytes * height_dots], row_bytes)
    else:
        out += gs_raster(raw[: row_bytes * height_dots], width_dots, height_dots)
    if line_dots:
        out += esc_feed(line_dots)
    return bytes(out)


# --------------------------------------------------------------------------- #
# 解析设备回包（打印机→主机，0xBB 开头）
# --------------------------------------------------------------------------- #
def parse_frames(buf: bytes) -> list[tuple[int, bytes]]:
    """从一段缓冲区里解析出 (cmd, payload)。不完整/坏校验的帧会被跳过。"""
    out: list[tuple[int, bytes]] = []
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] != START_PRINTER_TO_HOST:
            i += 1
            continue
        if i + 3 > n:
            break
        cmd = buf[i + 1]
        b2 = buf[i + 2]
        if b2 < 192:
            plen = b2
            pstart = i + 3
            crc_at = pstart + plen
        else:
            if i + 4 > n:
                break
            plen = ((b2 & 0x3F) << 8) | buf[i + 3]
            pstart = i + 4
            crc_at = pstart + plen
        if crc_at >= n:
            break
        payload = buf[pstart:crc_at]
        crc = buf[crc_at]
        # 校验判据：cmd + payload 各字节 + crc ≡ 0xFF (mod 256)
        if crc != NO_CRC_MARK and ((cmd + sum(payload) + crc) & 0xFF) != 0xFF:
            i += 1
            continue
        out.append((cmd, bytes(payload)))
        i = crc_at + 1
    return out


# --------------------------------------------------------------------------- #
# 演示
# --------------------------------------------------------------------------- #
def _demo() -> int:
    W, H = 384, 64
    row = (W + 7) // 8
    raw = bytearray(row * H)
    for y in range(H):
        for x in range(W):
            if (x // 24 + y // 16) % 2 == 0:
                raw[y * row + (x >> 3)] |= 0x80 >> (x & 7)

    stream = job_from_1bpp(bytes(raw), W, H, line_dots=32)
    print(f"  画布 {W}x{H} 点，1bpp 数据 {len(raw)} 字节")
    print(f"  ESC/POS 字节流 {len(stream)} 字节：")
    hexs = stream.hex(" ")
    for i in range(0, len(hexs), 96):
        print("   ", hexs[i:i + 96])

    # 再演示一帧控制命令（能力探测 0x79）
    f = frame(0x79)
    print(f"\n  控制帧 0x79 → {f.hex(' ')}")

    # 反解一层，验证自洽
    print("\n  回包解析自检：")
    sample = bytes([START_PRINTER_TO_HOST, 0x01, 0x02, 0x10, 0x20])
    sample += bytes([checksum(0x01, b"\x10\x20")])
    print("    ", sample.hex(" "), "→", parse_frames(sample))
    return 0


def selftest() -> int:
    """不连设备也能跑的自检。"""
    fails = []

    def chk(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r} want {want!r}")
        print(f"  [{'OK ' if got == want else 'FAIL'}] {name}")

    chk("空帧 0x79", frame(0x79).hex(" "), "aa 79 00 86")
    chk("带载荷 0x40", frame(0x40, b"\x41\x01\x02\xff").hex(" "),
        "aa 40 04 41 01 02 ff 7c")
    chk("不校验", frame(0x79, no_crc=True).hex(" "), "aa 79 00 88")
    chk("cmd=0 透传", frame(0, b"\x1b\x4a\x05").hex(" "), "1b 4a 05")
    chk("长度 300（两字节）", encode_len(300).hex(" "), "c1 2c")
    chk("走纸 300 拆分", esc_feed(300).hex(" "), "1b 4a ff 1b 4a 2d")

    payload = bytes([0x10, 0x20])
    reply = bytes([0xBB, 0x79, len(payload)]) + payload + bytes([checksum(0x79, payload)])
    chk("回包解析", parse_frames(reply), [(0x79, payload)])
    bad = bytearray(reply)
    bad[-1] ^= 0xFF
    chk("坏校验被丢弃", parse_frames(bytes(bad)), [])
    chk("混杂数据只取有效帧", parse_frames(b"\x00\x11" + reply + b"\xff"), [(0x79, payload)])

    raster = gs_raster(bytes((384 + 7) // 8 * 2), 384, 2)
    chk("GS v 0 头", raster[:8].hex(" "), "1d 76 30 00 30 00 02 00")

    print()
    if fails:
        for f in fails:
            print("  ✗", f)
        return 1
    print("  全部通过 ✅")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dothantech 标签机协议参考实现")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("demo", help="生成一张测试图的打印字节流")
    sub.add_parser("test", help="不连设备的自检")

    f = sub.add_parser("frame", help="构造一帧命令")
    f.add_argument("code", help="命令码（十进制或 0x..）")
    f.add_argument("payload", nargs="?", default="", help="payload 的十六进制")
    f.add_argument("--crc", action="store_true", help="额外打印校验值")
    f.add_argument("--no-crc", action="store_true", help="校验位填 0x88（不校验）")

    a = sub.add_parser("esc", help="生成 ESC/POS 指令")
    a.add_argument("what", choices=["feed", "raster"])
    a.add_argument("n", help="feed：点数；raster：宽x高")

    args = ap.parse_args(argv)
    if args.cmd == "test":
        return selftest()
    if args.cmd == "demo" or not args.cmd:
        return _demo()
    if args.cmd == "frame":
        cmd = int(args.code, 0)
        payload = bytes.fromhex(args.payload.replace(" ", "")) if args.payload else b""
        f = frame(cmd, payload, no_crc=args.no_crc)
        print(f"  帧: {f.hex(' ')}")
        if args.crc:
            print(f"  校验: 0x{checksum(cmd, payload):02X}")
        return 0
    if args.cmd == "esc":
        if args.what == "feed":
            print(esc_feed(int(args.n, 0)).hex(" "))
        else:
            w, h = (int(x) for x in args.n.lower().split("x"))
            print(gs_raster(bytes((w + 7) // 8 * h), w, h).hex(" ")[:120] + " …")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
