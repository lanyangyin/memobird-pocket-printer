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

# 浓度档位 → (阈值, 横向膨化, 纵向膨化)
# 热敏打印机"发灰"时，光调阈值往往不够（细笔画会断），所以要配合笔画膨化。
DARKEN_PRESETS = {
    0: (128, 0, 0),      # 标准
    1: (152, 1, 0),      # 加深
    2: (172, 1, 1),      # 更黑
    3: (192, 2, 1),      # 最黑（细字会粘在一起，适合大字号/图形）
}


def dilate_black(raw: bytes, w: int, h: int, horiz: int = 0, vert: int = 0) -> bytes:
    """把黑点向周围膨胀（形态学 dilation）—— 补偿打印机偏浅，让笔画变粗。"""
    if horiz <= 0 and vert <= 0:
        return raw
    rb = (w + 7) // 8
    grid = [bytearray(w) for _ in range(h)]
    for y in range(h):
        base = y * rb
        row = grid[y]
        for x in range(w):
            if raw[base + (x >> 3)] & (0x80 >> (x & 7)):
                row[x] = 1

    if horiz > 0:
        for _ in range(horiz):
            for y in range(h):
                src = grid[y][:]
                row = grid[y]
                for x in range(w):
                    if src[x]:
                        if x > 0:
                            row[x - 1] = 1
                        row[x] = 1
                        if x < w - 1:
                            row[x + 1] = 1
    if vert > 0:
        for _ in range(vert):
            snap = [r[:] for r in grid]
            for y in range(h):
                for x in range(w):
                    if snap[y][x]:
                        if y > 0:
                            grid[y - 1][x] = 1
                        if y < h - 1:
                            grid[y + 1][x] = 1

    out = bytearray(rb * h)
    for y in range(h):
        base = y * rb
        row = grid[y]
        for x in range(w):
            if row[x]:
                out[base + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


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


def dither_to_raw(
    img: Image.Image,
    mode: DitherMode = "floyd",
    threshold: int | None = None,
    darken: int = 0,
) -> tuple[int, int, bytes]:
    """
    灰度图 → (w, h, 1bpp 裸位图)，1=黑点，MSB 在左，行按字节对齐。

    darken: 0=标准 / 1=加深 / 2=更黑 / 3=最黑
            热敏打印偏浅时用它：提高阈值 + 笔画膨化（见 DARKEN_PRESETS）。
    threshold: 显式指定二值化阈值；不给就按 darken 档位取默认值。
    """
    preset_th, h_exp, v_exp = DARKEN_PRESETS.get(int(darken or 0), DARKEN_PRESETS[0])
    th = preset_th if threshold is None else int(threshold)

    g = img.convert("L")
    w, h = g.size
    px = list(g.getdata())

    if mode in ("none", "threshold"):
        raw = _pack_threshold(px, w, h, th)
        return w, h, dilate_black(raw, w, h, h_exp, v_exp)

    if mode == "bayer":
        out = bytearray((w + 7) // 8 * h)
        rb = (w + 7) // 8
        for y in range(h):
            brow = _BAYER8[y & 7]
            base, row = y * rb, y * w
            for x in range(w):
                t = (brow[x & 7] + 0.5) * 255.0 / 64.0 * (th / 128.0)
                if px[row + x] < t:
                    out[base + (x >> 3)] |= 0x80 >> (x & 7)
        return w, h, dilate_black(bytes(out), w, h, h_exp, v_exp)

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
            new = 255.0 if old >= th else 0.0
            buf[i] = new
            err = old - new
            if err:
                for dx, dy, k in kernels[mode]:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        buf[ny * w + nx] += err * k
    raw = _pack_threshold([int(v) for v in buf], w, h, th)
    return w, h, dilate_black(raw, w, h, h_exp, v_exp)


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
def raw_to_bmp(w: int, h: int, raw: bytes, top_down: bool = True, official: bool = True) -> bytes:
    """
    1bpp 裸位图 → BMP 字节流。**official 模式下与 PIL 的 1-bit BMP 逐字节一致**
    —— 官方 SDK 走的就是 PIL 那条编码路径，实机验证过的驱动都用它。

    两个必须踩对的点：
      1. **调色板顺序**：index0=黑、index1=白（PIL 就这样）。我们内部裸位图 bit=1 表示黑，
         而 BMP 里 bit=1 指向 index1=白 —— 所以写行数据时要**逐字节取反**。
         顺序/极性搞反 ⇒ 固件把整页当无效内容（实测：打出自带的 "nice to meet you" 示范页）。
      2. **行序与 biHeight**：official 时 biHeight 取正、但数据按 top-down 行序写
         （官方 `BMPFile.createBMPArray` 的非标准做法）；写负高度固件不认。

    official=False 时按 BMP 规范写（top_down=True → 负高度；False → 正高度 + bottom-up）。
    """
    row_bytes = ((w + 31) // 32) * 4
    src_rb = (w + 7) // 8
    body = bytearray()

    if official:
        ys = range(h)
        height_field = h
    else:
        ys = range(h) if top_down else range(h - 1, -1, -1)
        height_field = -h if top_down else h

    for y in ys:
        row = bytearray(row_bytes)
        src = raw[y * src_rb:(y + 1) * src_rb]
        for i, b in enumerate(src):
            row[i] = b ^ 0xFF               # bit=1(黑) → 0；取反后 bit=1 表示白(index1)
        body += row

    dib = struct.pack("<IiiHHIIiiII", 40, w, height_field, 1, 1, 0, len(body),
                      3780, 3780, 2, 2)
    palette = struct.pack("<II", 0x00000000, 0x00FFFFFF)   # 0=黑 1=白（与 PIL 一致）
    off = 14 + len(dib) + len(palette)
    fh = struct.pack("<2sIHHI", b"BM", off + len(body), 0, 0, off)
    return fh + dib + palette + bytes(body)


def image_to_bmp(img: Image.Image, mode: DitherMode = "floyd") -> bytes:
    w, h, raw = dither_to_raw(img, mode)
    return raw_to_bmp(w, h, raw, official=True)


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
