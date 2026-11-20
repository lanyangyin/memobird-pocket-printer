"""P1 协议 / 渲染的单元测试 —— 全部用真机抓到的回包做基准。

跑法： python tests/test_weida.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "weida"))

import weida_protocol as W  # noqa: E402

PASS = []
FAIL = []


def check(name, got, want):
    if got == want:
        PASS.append(name)
        print(f"  [OK ] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}\n         got  = {got!r}\n         want = {want!r}")


def check_true(name, cond, detail=""):
    check(name, bool(cond), True) if cond else check(name + (f" ({detail})" if detail else ""), False, True)


# --------------------------------------------------------------------------- #
print("=== 帧构造（真机验证过的字节）===")
check("状态查询 0x70", W.frame(0x70).hex(" "), "1f 70 00 8f")
check("设备名 0x79", W.frame(0x79).hex(" "), "1f 79 00 86")
check("开启设置 0x80 [7f]", W.frame(0x80, b"\x7f").hex(" "), "1f 80 01 7f ff")
check("ADC 电量 0x88 [01]", W.frame(0x88, b"\x01").hex(" "), "1f 88 01 01 75")
check("不校验", W.frame(0x79, no_crc=True).hex(" "), "1f 79 00 88")
check("cmd=0 透传", W.frame(0, b"\x1b\x40").hex(" "), "1b 40")

print("\n=== 帧解析（真机回包）===")
real_name = bytes.fromhex("1f 79 0c 50 31 2d 36 31 30 38 35 39 33 30 00 2c")
got = W.parse_frames(real_name)
check("设备名帧数量", len(got), 1)
check("设备名帧 cmd", got[0][0], 0x79)
check("设备名内容", W.decode_text(got[0][1]), "P1-61085930")

real_status = bytes.fromhex(
    "1f 70 1c 00 02 02 96 f1 36 01 24 00 00 00 00 00 00 00 00 00 00 79 02 05 00 c6 00 f0 13 3e 0c fa")
gs = W.parse_frames(real_status)
check("状态帧解析成功", len(gs), 1)
check("状态码 0 = 可打印", W.decode_status(gs[0][1])["text"], "可打印")

# 校验错误必须丢弃
bad = bytearray(real_name)
bad[-1] ^= 0xFF
check("坏校验被丢弃", len(W.parse_frames(bytes(bad))), 0)
# 0x88 免校验
nocr = bytearray(real_name)
nocr[-1] = 0x88
check("0x88 免校验可解", len(W.parse_frames(bytes(nocr))), 1)
# 长帧（两字节长度）
long_payload = bytes(range(200))
lf = bytearray([0x1F, 0x79, 0xC0 | (200 >> 8), 200 & 0xFF]) + long_payload
lf.append((~sum(lf[1:])) & 0xFF)
pl = W.parse_frames(bytes(lf))
check("两字节长度帧", (pl[0][0], len(pl[0][1])), (0x79, 200))

print("\n=== EBV ===")
check("EBV 0", W.ebv(0).hex(" "), "00")
check("EBV 191", W.ebv(191).hex(" "), "bf")
check("EBV 192", W.ebv(192).hex(" "), "c0 c0")
check("EBV 300", W.ebv(300).hex(" "), "c1 2c")
check("EBV 解码 300", W.debv(bytes([0xC1, 0x2C])), (300, 2))
check("EBV 解码 191", W.debv(bytes([0xBF])), (191, 1))

print("\n=== 设置解析（真机回包）===")
d = W.decode_darkness(bytes([5, 15, 1, 4]))
check("浓度当前值", d["level"], 5)
check("浓度最大值", d["max"], 15)
check("浓度最小值", d["min"], 1)
check("间隙长度 3.00mm", W.decode_gap_len(bytes([0xC1, 0x2C]))["mm"], 3.0)
c = W.decode_counters(bytes.fromhex("00000d5b00000d59000003 9c00000015".replace(" ", "")))
check("打印计数", c["total"], 3419)
check("打印计数 4 个", len(c["values"]), 4)
check("软件版本", W.decode_version(b"3.1.20260924\x00"), "3.1.20260924")
check("纸张类型文字", W.GAP_TYPES[2], "间隙纸(不干胶)")

print("\n=== 电量 / 温度（真机回包）===")
bat = W.decode_adc(bytes.fromhex(
    "01 01 88 01 87 01 87 01 87 00 00 10 41 ff 00 00 1e 0c 40"))
check("电量电压", bat["battery_v"], 3.91)
check("电量格数", bat["battery_level"], 65)
check("充电状态", bat["charging"], False)
t = W.decode_adc(bytes.fromhex("02 00 d9 00 0a 09 7f ff 7f ff"))
check("打印头温度", t["head_temp_c"], 21.7)

print("\n=== 标签打印流 ===")
rows = bytes(40 * 3)
stream = W.label_stream(rows, 320, 3, width_mm=40)
check("以 1B 40 开头", stream[:2].hex(" "), "1b 40")
check("设宽度 40mm", stream[2:7].hex(" "), "1f 27 01 28 88")
check("以 0C 结尾", stream[-1:].hex(" "), "0c")
check_true("含 1F 2A 行命令", b"\x1f\x2a" in stream)
# 全同一行的压缩：应该只有一个 1F 2A + 一个重复命令
same = bytes(40) * 10
s2 = W.label_stream(same, 320, 10, width_mm=40)
check_true("重复行被压缩", s2.count(b"\x1f\x2a") == 1 and b"\x1f\x2e" in s2)

print("\n=== 渲染 ===")
from p1_client import render_qr, render_text  # noqa: E402


def ink(raw):
    return sum(bin(b).count("1") for b in raw)


raw, w, h = render_text("测试 text", width_mm=40, height_mm=30)
check("文本尺寸 320x240", (w, h), (320, 240))
check("文本字节数", len(raw), 9600)
check_true("文本有墨", ink(raw) > 100)

qraw, qw, qh = render_qr("https://example.com", caption="P1")
check("二维码尺寸", (qw, qh), (320, 240))
check_true("二维码有墨", ink(qraw) > 500)
check_true("二维码比文本墨多", ink(qraw) > ink(raw))

print("\n=== 命令行 ===")
check("frame 子命令", W.frame(0x70).hex(" "), "1f 70 00 8f")

# --------------------------------------------------------------------------- #
print()
if FAIL:
    print(f"失败 {len(FAIL)} 项: {FAIL}")
    sys.exit(1)
print(f"全部通过 ✅（{len(PASS)} 项）")
