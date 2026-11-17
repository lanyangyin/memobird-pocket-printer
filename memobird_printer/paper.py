"""
memobird_printer/paper.py — 走纸 / 纸张长度控制

热敏打印头是 203 dpi ⇒ **8 点/毫米**（1 dot = 0.125 mm）。所以有两档精度：

| 方式 | 精度 | 做法 |
|---|---|---|
| 空白位图 | **精确按点数**（±1 点 = ±0.125 mm） | 打一张全白位图，高 N 点 ⇒ 走 N/8 mm |
| 换行文本 | 粗（一行 = 固件字高） | 发 `\\n` 的文本帧 |

空白位图这条路不显色但纸照样被送过去 —— 这是唯一能"打指定长度"的手法。

⚠️ 少数固件会把整幅全白当作"没东西要打"直接跳过。
   遇到这种情况给 `tick=True`：在上边缘画 1 点黑，几乎看不出来，但能触发走纸。
"""
from __future__ import annotations

from . import packet

DOTS_PER_MM_203 = 8.0        # 203 dpi / 25.4mm ≒ 8 dots/mm

# 固件每个打印任务固定多喂的纸（实机实测，GT1）：
#   任务开始 11mm + 任务结束 7mm = 18mm
# 所以「出纸总长 = 内容高度 + OVERHEAD_MM」——想要总长 N，内容就画 N-18。
OVERHEAD_MM = 18.0

# 单个打印任务能完整打出的最大高度。
# 注意：早期实测"400 行以上会断"其实是**丢数据**（发送太快、固件缓冲吃不下），
# 修好"逐帧流控 + 提交前等最后一帧 ack"之后，496 行（62mm）和 800 行（100mm）
# 单任务都能完整打出来。所以这里只是一个保守的分页阈值，
# 不是硬件硬限制；Python 侧默认走流控，不再需要分页。
MAX_ROWS_PER_JOB = 1200

# 不发终结帧（--exact）时曾经"15 帧出白纸"，但那也是**丢数据**造成的假象。
# 修好逐帧流控 + 提交前等 ack 之后，496 行（24 帧 / 62mm）用 --exact 能完整打出，
# 而且最后一行直接贴在纸边（尾部 0mm）。
# 这个常量只留给"要不要提醒用户"用，不再是硬限制。
EXACT_SAFE_FRAMES = 200
DOTS_PER_MM_300 = 11.811     # G4 之类 300dpi 机型（按机型调）


def mm_to_dots(mm: float, dpi: int = 203) -> int:
    dots_per_mm = DOTS_PER_MM_203 if dpi <= 203 else DOTS_PER_MM_300
    return max(1, round(mm * dots_per_mm))


def blank_raw(width: int, height: int, *, tick: bool = False) -> bytes:
    """生成一张全白的 1bpp 裸位图（1=黑）；tick=True 时在第 1 行第 1 点画一个黑点。"""
    row_bytes = (width + 7) // 8
    raw = bytearray(row_bytes * height)
    if tick and raw:
        raw[0] |= 0x80
    return bytes(raw)


def content_dots_for_total(total_mm: float, dpi: int = 203,
                           overhead_mm: float = OVERHEAD_MM) -> int:
    """想要纸总长 total_mm，内容该画多少点（扣掉固件固定多喂的 18mm）。"""
    return max(1, mm_to_dots(max(1.0, total_mm - overhead_mm), dpi))


def blank_frames(mm: float | None = None, *, dots: int | None = None, width: int = 384,
                 dpi: int = 203, tick: bool = False,
                 total: bool = False) -> tuple[list[bytes], dict]:
    """走纸任务：全白位图 → BMP → 分帧。返回 (frames, meta)。

    total=True 时 mm 表示「纸总长」，会自动扣掉固件固定多喂的 18mm。
    """
    from .image import raw_to_bmp

    if dots is not None:
        h = dots
    elif total:
        h = content_dots_for_total(mm or 0, dpi)
    else:
        h = mm_to_dots(mm or 0, dpi)
    h = max(1, min(int(h), 30000))            # 别让人一次走 30 米
    raw = blank_raw(width, h, tick=tick)
    bmp = raw_to_bmp(width, h, raw, official=True)
    job = packet.build_bmp_job(bmp)
    meta = {"kind": "feed", "dots": h, "mm": round(h / (DOTS_PER_MM_203 if dpi <= 203 else DOTS_PER_MM_300), 2),
            "dpi": dpi, "width": width, "bytes": len(bmp), "chunks": job.chunks,
            "preheat": packet.PREHEAT, "tick": tick}
    return list(job.frames), meta


def line_frames(lines: int = 3) -> tuple[list[bytes], dict]:
    """按行喂纸（粗）：发 N 个换行的文本帧。"""
    n = max(1, min(int(lines), 200))
    job = packet.feed_job(n)
    return list(job.frames), {"kind": "feed-lines", "lines": n, "chunks": job.chunks,
                              "bytes": job.total_bytes, "preheat": packet.PREHEAT}


# --------------------------------------------------------------------------- #
# 让整张纸正好 N 毫米：给内容补白 / 裁切到目标高度
# --------------------------------------------------------------------------- #
def pad_to_length(img, mm: float, *, dpi: int = 203, align: str = "top",
                  total: bool = False, overhead_mm: float = OVERHEAD_MM):
    """
    把灰度图补白（或裁切）到正好 `mm` 毫米高。

    出纸总长 = 位图高度，所以这是"整张纸正好 N mm"的唯一可靠做法
    （走纸是额外再送，不能保证内容本身占多长）。

    align: top / center / bottom —— 内容放在目标高度的哪个位置。
    """
    from PIL import Image

    if total:
        target = content_dots_for_total(mm, dpi, overhead_mm)
    else:
        target = mm_to_dots(mm, dpi)
    w, h = img.size
    if h == target:
        return img
    if h > target:
        return img.crop((0, 0, w, target))

    canvas = Image.new("L", (w, target), 255)
    if align == "bottom":
        y = target - h
    elif align == "center":
        y = (target - h) // 2
    else:
        y = 0
    canvas.paste(img, (0, y))
    return canvas


# --------------------------------------------------------------------------- #
# 长图分段（绕过 BLE 吞吐不足）
# --------------------------------------------------------------------------- #
def split_image(img, segment_mm: float = 15, *, dpi: int = 203):
    """
    把长图切成若干段，每段高度 ≈ segment_mm。

    为什么需要：Windows 的 BLE 写入吞吐约 3 KB/s，而打印机是一边收一边打。
    实测超过约 25 mm 的内容会"中途断粮"直接停住 —— 所以长图必须分段，
    每段单独打印、各自带终结帧，打印机就会连续吐纸。
    """
    seg = max(1, mm_to_dots(segment_mm, dpi))
    w, h = img.size
    out = []
    for y in range(0, h, seg):
        out.append(img.crop((0, y, w, min(y + seg, h))))
    return out


# --------------------------------------------------------------------------- #
# 大图自动分页
# --------------------------------------------------------------------------- #
def paginate(img, max_rows: int = MAX_ROWS_PER_JOB):
    """
    把超过单任务上限的图切成多页（每页 ≤ max_rows 行）。

    为什么需要：GT1 单任务超过约 400 行就只会打出开头一点点（实测 480 行失败）。
    代价：页与页之间会有固件固定的 18mm 空隙，抹不掉。
    """
    w, h = img.size
    if h <= max_rows:
        return [img]
    return [img.crop((0, y, w, min(y + max_rows, h))) for y in range(0, h, max_rows)]
