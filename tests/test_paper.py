#!/usr/bin/env python3
"""
tests/test_paper.py — 走纸（指定长度）的数学与帧构造

    python tests/test_paper.py

核心假设：打印头 203 dpi ⇒ 8 点/毫米。这条要是错了，走纸长度就会整体偏。
实机验证方式：打一张「黑杠 + 50mm 空白 + 黑杠」的标定图，用尺量中间空白。
"""
from __future__ import annotations

import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from memobird_printer import packet, paper      # noqa: E402

fails: list[str] = []
passes = 0


def check(name, cond, detail=""):
    global passes
    if cond:
        passes += 1
        print(f"  [OK ] {name}{('  ' + detail) if detail else ''}")
    else:
        fails.append(name)
        print(f"  [FAIL] {name}{('  ' + detail) if detail else ''}")


print("1) 毫米 ↔ 点数（203dpi = 8 点/mm）")
check("1mm = 8 点", paper.mm_to_dots(1) == 8, str(paper.mm_to_dots(1)))
check("50mm = 400 点", paper.mm_to_dots(50) == 400, str(paper.mm_to_dots(50)))
check("0.5mm 取整到 4 点", paper.mm_to_dots(0.5) == 4, str(paper.mm_to_dots(0.5)))
check("0mm 也至少 1 点", paper.mm_to_dots(0) == 1, str(paper.mm_to_dots(0)))
check("300dpi 换算不同", paper.mm_to_dots(10, dpi=300) != paper.mm_to_dots(10, dpi=203),
      f"{paper.mm_to_dots(10, dpi=203)} vs {paper.mm_to_dots(10, dpi=300)}")

print("\n2) 全白位图")
raw = paper.blank_raw(384, 10)
check("行字节 = 48", len(raw) == 48 * 10, str(len(raw)))
check("全零 = 全白", set(raw) == {0}, str(sorted(set(raw))))
raw_tick = paper.blank_raw(384, 10, tick=True)
check("tick 只改第 1 个字节", raw_tick[0] == 0x80 and raw_tick[1:] == raw[1:])
check("tick 后仍只有 1 个黑点", sum(bin(b).count("1") for b in raw_tick) == 1)

print("\n3) 走纸任务（20mm）")
frames, meta = paper.blank_frames(mm=20)
check("点数 = 160", meta["dots"] == 160, str(meta["dots"]))
check("毫米回显 = 20.0", meta["mm"] == 20.0, str(meta["mm"]))
check("BMP 字节 = 62 + 48*160", meta["bytes"] == 62 + 48 * 160, str(meta["bytes"]))
check("帧数 = ceil(7742/1024) = 8", meta["chunks"] == 8, str(meta["chunks"]))
check("帧数与 meta 一致", len(frames) == 8, str(len(frames)))
check("每帧都是合法打印命令", all(f[3] == packet.CMD_PRINT for f in frames))
check("首帧能解析", packet.parse_frame(frames[0]) is not None)

print("\n4) 边界")
f2, m2 = paper.blank_frames(dots=1)
check("1 点也能组帧", len(f2) >= 1 and m2["dots"] == 1)
f3, m3 = paper.blank_frames(mm=100000)
check("超大值被钳到 30000 点", m3["dots"] == 30000, str(m3["dots"]))

print("\n5) 按行走纸（粗）")
lf, lm = paper.line_frames(3)
check("3 行 = 1 帧", len(lf) == 1, str(len(lf)))
check("3 行 3 字节", lm["bytes"] == 3, str(lm["bytes"]))
check("帧里是 3 个换行", packet.parse_frame(lf[0]) is not None)

print("\n6) 整页长度（内容补白到 N 毫米）")
from memobird_printer.image import prepare          # noqa: E402

img = prepare("测试")
base_h = img.size[1]
for mm, want in ((30, 240), (60, 480), (100, 800)):
    out = paper.pad_to_length(img, mm)
    check(f"{mm}mm → {want} 点", out.size[1] == want, f"{out.size[1]} 点")
    check(f"{mm}mm 宽度不变", out.size[0] == 384, str(out.size[0]))
trimmed = paper.pad_to_length(img, 5)
check("内容比目标高时裁切", trimmed.size[1] == 40, str(trimmed.size[1]))
check("裁切后宽度不变", trimmed.size[0] == 384)
bottom = paper.pad_to_length(img, 60, align="bottom")
check("bottom 对齐仍是 480 点", bottom.size[1] == 480)

print("\n7) 固件固定多喂 18mm 的补偿（实机：上 11 + 下 7）")
check("常量 = 18mm", paper.OVERHEAD_MM == 18.0, str(paper.OVERHEAD_MM))
check("总长 40mm → 内容 176 点", paper.content_dots_for_total(40) == 176,
      str(paper.content_dots_for_total(40)))
check("总长 58mm → 内容 320 点（= 实机 40mm 图那张）",
      paper.content_dots_for_total(58) == 320, str(paper.content_dots_for_total(58)))
check("总长小于 18mm 时，内容取最小 1mm = 8 点", paper.content_dots_for_total(10) == 8,
      str(paper.content_dots_for_total(10)))
f40, m40 = paper.blank_frames(mm=40, total=True)
check("blank_frames(total) 内容 = 22mm", m40["dots"] == 176, str(m40["dots"]))

print("\n8) 单任务高度上限与分页")
from PIL import Image                                # noqa: E402

check("分页阈值 = 1200 行（流控后单任务可到 100mm+）", paper.MAX_ROWS_PER_JOB == 1200,
      str(paper.MAX_ROWS_PER_JOB))
check("400 行不分页", len(paper.paginate(Image.new("L", (384, 400)))) == 1)
check("800 行也不分页", len(paper.paginate(Image.new("L", (384, 800)))) == 1)
check("1300 行分 2 页", len(paper.paginate(Image.new("L", (384, 1300)))) == 2)
check("2500 行分 3 页", len(paper.paginate(Image.new("L", (384, 2500)))) == 3)
pages = paper.paginate(Image.new("L", (384, 2500)))
check("分页后总行数不变", sum(p.size[1] for p in pages) == 2500,
      str(sum(p.size[1] for p in pages)))
check("每页宽度不变", all(p.size[0] == 384 for p in pages))

print("\n9) 不发终结帧（--exact）的安全上限")
check("提示阈值 = 200 帧（不再是硬限制）", paper.EXACT_SAFE_FRAMES == 200,
      str(paper.EXACT_SAFE_FRAMES))
# 13 帧 ≈ 34mm；15 帧实测出白纸
from memobird_printer.image import raw_to_bmp           # noqa: E402

rows_13 = len(packet.build_bmp_job(
    raw_to_bmp(384, 276, bytes(48 * 276), official=True)).frames)
check("34mm 内容 ≈ 13 帧", rows_13 == 13, str(rows_13))
rows_15 = len(packet.build_bmp_job(
    raw_to_bmp(384, 318, bytes(48 * 318), official=True)).frames)
check("40mm 内容 ≈ 15 帧（超过安全上限）", rows_15 == 15, str(rows_15))

print()
if fails:
    print(f"失败 {len(fails)} 项: {fails}")
    sys.exit(1)
print(f"全部通过 ✅（{passes} 项）")
