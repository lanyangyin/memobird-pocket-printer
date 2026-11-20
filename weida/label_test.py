"""40x30mm 不干胶标签 —— 标定测试

打印头 384 点 = 48mm，标签纸 40mm = 320 点。
所以画布用 384 宽，内容居中放在中间 320 点里，两侧各留 32 点空白。

用法：
    python label_test.py                 # 打标定图（边框 + 网格 + 文字）
    python label_test.py --feed 0        # 不打完不走纸
    python label_test.py --addr xx       # 指定地址
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import weida_protocol as W  # noqa: E402
from p1_client import P1Client  # noqa: E402

HEAD_DOTS = 384          # 打印头
LABEL_W_DOTS = 320       # 40mm
LABEL_H_DOTS = 240       # 30mm
SIDE = (HEAD_DOTS - LABEL_W_DOTS) // 2   # 32


def canvas(width: int = HEAD_DOTS, height: int = LABEL_H_DOTS) -> bytearray:
    return bytearray(((width + 7) // 8) * height)


def put_px(buf: bytearray, width: int, x: int, y: int, on: bool = True) -> None:
    if x < 0 or y < 0 or x >= width or y >= len(buf) * 8 // ((width + 7) // 8):
        return
    row = (width + 7) // 8
    idx = y * row + (x >> 3)
    if idx >= len(buf):
        return
    if on:
        buf[idx] |= 0x80 >> (x & 7)
    else:
        buf[idx] &= ~(0x80 >> (x & 7)) & 0xFF


def rect(buf: bytearray, width: int, x0: int, y0: int, x1: int, y1: int, thick: int = 1) -> None:
    for t in range(thick):
        for x in range(x0, x1 + 1):
            put_px(buf, width, x, y0 + t)
            put_px(buf, width, x, y1 - t)
        for y in range(y0, y1 + 1):
            put_px(buf, width, x0 + t, y)
            put_px(buf, width, x1 - t, y)


def draw_text(buf: bytearray, width: int, x: int, y: int, text: str, size: int = 16) -> None:
    """用 PIL 画字再贴进位图（1=黑）。"""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("msyh.ttc", size)
    except Exception:                                # noqa: BLE001
        font = ImageFont.load_default()
    img = Image.new("L", (420, size + 8), 255)
    ImageDraw.Draw(img).text((0, 2), text, font=font, fill=0)
    px = img.load()
    row = (width + 7) // 8
    for yy in range(img.height):
        for xx in range(img.width):
            if px[xx, yy] < 128:
                gx, gy = x + xx, y + yy
                if 0 <= gx < width and gy * row < len(buf):
                    put_px(buf, width, gx, gy)


def calibration(width: int = HEAD_DOTS) -> tuple[bytes, int, int]:
    """40x30 标定图：外框 = 标签边界，网格每 5mm，文字标尺寸。"""
    h = LABEL_H_DOTS
    buf = canvas(width, h)
    x0, x1 = SIDE, SIDE + LABEL_W_DOTS - 1
    y0, y1 = 0, h - 1
    rect(buf, width, x0, y0, x1, y1, thick=2)

    # 每 5mm（40 点）画一条内侧刻线
    for mm in range(5, 40, 5):
        x = x0 + mm * 8
        for y in range(8, 24):
            put_px(buf, width, x, y)
        for y in range(h - 24, h - 8):
            put_px(buf, width, x, y)
    for mm in range(5, 30, 5):
        y = y0 + mm * 8
        for x in range(x0 + 6, x0 + 26):
            put_px(buf, width, x, y)

    draw_text(buf, width, x0 + 40, 30, "40 x 30 mm", 28)
    draw_text(buf, width, x0 + 40, 80, "320 x 240 dots", 20)
    draw_text(buf, width, x0 + 40, 120, "P1 label test", 20)
    draw_text(buf, width, x0 + 40, 170, "边界=外框", 20)
    return bytes(buf), width, h


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="40x30mm 标签标定打印")
    ap.add_argument("--addr", default="28:D4:1E:9A:99:DB")
    ap.add_argument("--feed", type=int, default=0,
                    help="打完额外走纸点数（默认 0，交给间隙传感器）")
    ap.add_argument("--plain", action="store_true", help="只打 320 宽的图，不居中")
    args = ap.parse_args(argv)

    if args.plain:
        buf = canvas(LABEL_W_DOTS, LABEL_H_DOTS)
        rect(buf, LABEL_W_DOTS, 0, 0, LABEL_W_DOTS - 1, LABEL_H_DOTS - 1, thick=2)
        draw_text(buf, LABEL_W_DOTS, 10, 40, "320 wide", 28)
        raw, w, h = bytes(buf), LABEL_W_DOTS, LABEL_H_DOTS
    else:
        raw, w, h = calibration()

    async with P1Client(args.addr, echo=False) as p1:
        print(f"  画出 {w}x{h} 点（{w / 8:.0f}x{h / 8:.0f}mm），"
              f"内容{'居中在中间 320 点' if not args.plain else '从 0 开始'}")
        ok = await p1.print_1bpp(raw, w, h, feed_dots=args.feed)
        print(f"  发送 {p1.sent_bytes} 字节 → {'成功' if ok else '中断'}")
        await asyncio.sleep(1.5)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
