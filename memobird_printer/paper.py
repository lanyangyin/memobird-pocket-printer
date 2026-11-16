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


def blank_frames(mm: float | None = None, *, dots: int | None = None, width: int = 384,
                 dpi: int = 203, tick: bool = False) -> tuple[list[bytes], dict]:
    """走纸任务：全白位图 → BMP → 分帧。返回 (frames, meta)。"""
    from .image import raw_to_bmp

    h = dots if dots is not None else mm_to_dots(mm or 0, dpi)
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
