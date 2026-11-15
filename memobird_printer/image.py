"""
memobird/image.py — 打印图像/文字预处理

把任意文本/图片变成热敏打印机要的 **384 点宽 1bpp 位图**，并输出各后端所需格式：
  * BMP(top-down, 负 biHeight)  → 云端 API `P:` / 局域网 HTTP
  * 裸位图字节(MSB first)        → 蓝牙 TLV

咕咕机 / 有道口袋打印机：打印头 384 dots，纸宽 57mm（G1/G2 203dpi，G4 300dpi）。
"""
from __future__ import annotations

import os
import struct
from typing import Literal, Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps

PRINTER_WIDTH = 384
DitherMode = Literal["none", "floyd", "atkinson", "bayer", "threshold"]

_DEFAULT_FONTS = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def find_font(preferred: str | None = None, size: int = 24) -> ImageFont.FreeTypeFont:
    for path in ([preferred] if preferred else []) + _DEFAULT_FONTS:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


# --------------------------------------------------------------------------- #
# 文字渲染
# --------------------------------------------------------------------------- #
def render_text(
    text: str,
    *,
    font: str | None = None,
    font_size: int = 24,
    line_spacing: int = 6,
    width: int = PRINTER_WIDTH,
    padding: int = 4,
) -> Image.Image:
    """多行文本 → width 宽的灰度图（白底黑字，自动按像素宽度换行）。"""
    f = find_font(font, font_size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        cur = ""
        for ch in line:
            if probe.textlength(cur + ch, font=f) > width - 2 * padding:
                wrapped.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            wrapped.append(cur)

    ascent, descent = f.getmetrics()
    line_h = ascent + descent + line_spacing
    height = max(line_h * len(wrapped) + 2 * padding, line_h)
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    y = padding
    for line in wrapped:
        d.text((padding, y), line, font=f, fill=0)
        y += line_h
    return img


# --------------------------------------------------------------------------- #
# 缩放 / 抖动
# --------------------------------------------------------------------------- #
def fit_width(img: Image.Image, width: int = PRINTER_WIDTH, allow_upscale: bool = True) -> Image.Image:
    img = img.convert("L")
    ratio = width / img.width
    if ratio < 1 or allow_upscale:
        nh = max(1, round(img.height * ratio))
        img = img.resize((width, nh), Image.LANCZOS)
    canvas = Image.new("L", (width, img.height), 255)
    canvas.paste(img, ((width - img.width) // 2, 0))
    return canvas


_BAYER8 = (
    (0, 32, 8, 40, 2, 34, 10, 42), (48, 16, 56, 24, 50, 18, 58, 26),
    (12, 44, 4, 36, 14, 46, 6, 38), (60, 28, 52, 20, 62, 30, 54, 22),
    (3, 35, 11, 43, 1, 33, 9, 41), (51, 19, 59, 27, 49, 17, 57, 25),
    (15, 47, 7, 39, 13, 45, 5, 37), (63, 31, 55, 23, 61, 29, 53, 21),
)


def _pack_threshold(gray_px: Sequence[int], w: int, h: int, threshold: int) -> bytes:
    rb = (w + 7) // 8
    out = bytearray(rb * h)
    for y in range(h):
        base = y * rb
        row = y * w
        for x in range(w):
            if gray_px[row + x] < threshold:
                out[base + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


def dither_to_raw(img: Image.Image, mode: DitherMode = "floyd", threshold: int = 128) -> tuple[int, int, bytes]:
    """灰度图 → (w, h, 1bpp 裸位图)，1=黑点，MSB 在左，行按字节对齐。"""
    g = img.convert("L")
    w, h = g.size
    px = list(g.getdata())

    if mode in ("none", "threshold"):
        return w, h, _pack_threshold(px, w, h, threshold)

    if mode == "bayer":
        out = bytearray((w + 7) // 8 * h)
        rb = (w + 7) // 8
        for y in range(h):
            brow = _BAYER8[y & 7]
            base, row = y * rb, y * w
            for x in range(w):
                t = (brow[x & 7] + 0.5) * 255.0 / 64.0
                if px[row + x] < t:
                    out[base + (x >> 3)] |= 0x80 >> (x & 7)
        return w, h, bytes(out)

    kernels = {
        "floyd": ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)),
        "atkinson": ((1, 0, 1 / 8), (2, 0, 1 / 8), (-1, 1, 1 / 8), (0, 1, 1 / 8), (1, 1, 1 / 8), (0, 2, 1 / 8)),
    }
    if mode not in kernels:
        raise ValueError(f"unknown dither mode: {mode}")

    buf = [float(v) for v in px]
    for y in range(h):
        for x in range(w):
            i = y * w + x
            old = buf[i]
            new = 255.0 if old >= threshold else 0.0
            buf[i] = new
            err = old - new
            if err:
                for dx, dy, k in kernels[mode]:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        buf[ny * w + nx] += err * k
    return w, h, _pack_threshold([int(v) for v in buf], w, h, threshold)


def raw_to_image(w: int, h: int, raw: bytes) -> Image.Image:
    """裸位图 → 1-bit 图像（便于预览/调试）。"""
    return _raw_to_1bit(w, h, raw)


def _raw_to_1bit(w: int, h: int, raw: bytes) -> Image.Image:
    rb = (w + 7) // 8
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            if raw[y * rb + (x >> 3)] & (0x80 >> (x & 7)):
                out[y * w + x] = 0
            else:
                out[y * w + x] = 255
    return Image.frombytes("L", (w, h), bytes(out)).convert("1")


# --------------------------------------------------------------------------- #
# 输出格式
# --------------------------------------------------------------------------- #
def raw_to_bmp(w: int, h: int, raw: bytes, top_down: bool = True) -> bytes:
    """
    1bpp 裸位图 → BMP 字节流。
    top_down=True 时 biHeight 为负（行序 top-down）—— 咕咕机云/局域网接口要求如此，
    否则打出来上下颠倒。
    """
    row_bytes = ((w + 31) // 32) * 4
    src_rb = (w + 7) // 8
    body = bytearray()
    ys = range(h) if top_down else range(h - 1, -1, -1)
    for y in ys:
        row = bytearray(row_bytes)
        row[:src_rb] = raw[y * src_rb:(y + 1) * src_rb]
        body += row

    dib = struct.pack("<IiiHHIIiiII", 40, w, -h if top_down else h, 1, 1, 0, len(body), 2835, 2835, 2, 0)
    palette = struct.pack("<II", 0x00FFFFFF, 0x00000000)  # 0=白 1=黑
    off = 14 + len(dib) + len(palette)
    fh = struct.pack("<2sIHHI", b"BM", off + len(body), 0, 0, off)
    return fh + dib + palette + bytes(body)


def image_to_bmp(img: Image.Image, mode: DitherMode = "floyd") -> bytes:
    w, h, raw = dither_to_raw(img, mode)
    return raw_to_bmp(w, h, raw, top_down=True)


def prepare(
    src: str | Image.Image,
    *,
    mode: DitherMode = "floyd",
    width: int = PRINTER_WIDTH,
    font: str | None = None,
    font_size: int = 24,
    invert: bool = False,
) -> Image.Image:
    """文字或图片 → width 宽灰度图（下一步交给 dither_to_raw / image_to_bmp）。"""
    if isinstance(src, str):
        img = render_text(src, font=font, font_size=font_size, width=width)
    else:
        img = fit_width(src, width)
    if invert:
        img = ImageOps.invert(img.convert("L"))
    return img


def preview(img: Image.Image, path: str, mode: DitherMode = "floyd", scale: int = 2) -> str:
    """把抖动结果存成 PNG，方便肉眼核对（白底黑点，放大 scale 倍）。"""
    w, h, raw = dither_to_raw(img, mode)
    im = _raw_to_1bit(w, h, raw).convert("L")
    if scale > 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    im.save(path)
    return path
