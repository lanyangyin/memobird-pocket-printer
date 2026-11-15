#!/usr/bin/env python3
"""
tools/gen_fixtures.py — 生成 JS 编码器的对照夹具

用途：`web/encoder.js` 是 Python 编码器的 JS 复刻，要求**输出逐字节相同**。
      本脚本用 Python（已验证过的实现）产出一批输入/输出样本，
      再由 `tests/test_encoder_js.js`（Node）逐字节比对。

    python tools/gen_fixtures.py          # → tests/fixtures.json
"""
from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image                                   # noqa: E402
from memobird_printer import packet                     # noqa: E402
from memobird_printer.image import (                    # noqa: E402
    dither_to_raw, prepare, raw_to_bmp,
)


def gradient(w: int, h: int) -> Image.Image:
    """确定性灰图：x 方向 0→255，y 方向做一点变化，保证抖动有误差扩散。"""
    px = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            px[y * w + x] = (x * 255 // max(1, w - 1) + y * 7) % 256
    return Image.frombytes("L", (w, h), bytes(px))


def checker(w: int, h: int) -> Image.Image:
    px = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            px[y * w + x] = 0 if ((x // 3 + y // 3) % 2 == 0) else 255
    return Image.frombytes("L", (w, h), bytes(px))


def main() -> int:
    fixtures: dict = {"text_jobs": [], "dither": [], "bmp": [], "gbk": [], "frames": []}

    # ---- 1) 帧构造 ----
    fixtures["frames"] = [
        {"name": "led_on",
         "cmd": 3, "tlv": [[3, "01"]],
         "hex": packet.build_frame(packet.CMD_CONTROL, packet.tlv(0x03, b"\x01")).hex()},
        {"name": "status",
         "cmd": 1, "tlv": [],
         "hex": packet.build_frame(packet.CMD_STATUS).hex()},
        {"name": "print3",
         "cmd": 4,
         "tlv": [[0x0B, "0500"], [0x0C, "0100"], [0x0A, "2900"]],
         "hex": packet.build_frame(
             packet.CMD_PRINT,
             packet.tlv(0x0B, b"\x05\x00") + packet.tlv(0x0C, b"\x01\x00") + packet.tlv(0x0A, b"\x29\x00"),
         ).hex()},
    ]

    # ---- 2) 文本任务（GBK 帧，含样式 tag）----
    text_cases = [
        ("你好", False, False, 0),
        ("你好世界，这是一行普通的中文测试文本，一共二十多个字", True, False, 0),
        ("hello 123", False, True, 1),
        ("混合 mixed 内容 001", True, True, 2),
        ("长文本分包测试" * 40, False, False, 0),      # 触发 300 字节分包
    ]
    for text, bold, ul, size in text_cases:
        job = packet.job_for_text(text, encoding="gbk", bold=bold, underline=ul, font_size=size)
        fixtures["text_jobs"].append({
            "text": text,
            "bold": bold, "underline": ul, "fontSize": size,
            "gbk_hex": (text + "\n").encode("gbk").hex(),
            "frames_hex": [f.hex() for f in job.frames],
            "meta": {"format": "gbk", "chunks": job.chunks, "bytes": job.total_bytes},
        })

    # ---- 3) 抖动（裸位图）----
    cases = [
        ("gradient", gradient(64, 40), "floyd", 128, 0),
        ("gradient", gradient(64, 40), "atkinson", 128, 0),
        ("gradient", gradient(64, 40), "bayer", 128, 0),
        ("checker", checker(48, 33), "threshold", 128, 0),
        ("gradient", gradient(40, 24), "threshold", 96, 0),
        # 浓度档位：阈值偏移 + 笔画膨化（打浅时用）
        ("gradient", gradient(64, 40), "threshold", 128, 1),
        ("gradient", gradient(64, 40), "threshold", 128, 2),
        ("gradient", gradient(40, 24), "floyd", 128, 3),
        ("checker", checker(48, 33), "floyd", 128, 2),
    ]
    for name, img, mode, th, darken in cases:
        w, h, raw = dither_to_raw(img, mode, threshold=th, darken=darken)
        fixtures["dither"].append({
            "name": name, "w": w, "h": h, "mode": mode, "threshold": th, "darken": darken,
            "gray_hex": img.convert("L").tobytes().hex(),
            "raw_hex": raw.hex(),
        })

    # ---- 4) BMP（official 与规范写法都要对得上）----
    img = checker(48, 24)
    w, h, raw = dither_to_raw(img, "threshold")
    for td in (True, False):
        for official in (True, False):
            fixtures["bmp"].append({
                "w": w, "h": h, "raw_hex": raw.hex(),
                "top_down": td, "official": official,
                "bmp_hex": raw_to_bmp(w, h, raw, top_down=td, official=official).hex(),
            })

    # ---- 5) GBK 编码 ----
    for text in ["你好", "咕咕机", "abc 你好 123", "，。！？：；（）《》"]:
        fixtures["gbk"].append({"text": text, "hex": text.encode("gbk").hex()})

    out = os.path.join(ROOT, "tests", "fixtures.json")
    # newline="\n" 必须显式指定：Windows 上默认会把 \n 翻成 \r\n，
    # 导致 CI（Linux）重新生成后 git diff 不一致。
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(fixtures, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"fixtures: {out}")
    for k, v in fixtures.items():
        print(f"  {k}: {len(v)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
