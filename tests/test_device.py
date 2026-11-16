#!/usr/bin/env python3
"""
tests/test_device.py — 设备信息解析（memobird_printer/device.py）

    python tests/test_device.py

用实机抓到的那一帧（GT1，72 字节 cmd=0x0A 回包）做黄金样例，
不需要打印机：只要解析结果对得上，后面接上真机就能直接用。
"""
from __future__ import annotations

import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from memobird_printer import device, packet      # noqa: E402

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


# --------------------------------------------------------------------------- #
# 实机抓包还原：aa 44 00 0a | ff=01 01=17 02=0a 03=01 04=47 05=01 06=00 13=f0 | 0f=<32B SN>
SN = "636404963750" + "0" * 20
payload = (
    packet.tlv(0xFF, b"\x01")
    + packet.tlv(0x01, bytes([0x17]))
    + packet.tlv(0x02, bytes([0x0A]))
    + packet.tlv(0x03, bytes([0x01]))
    + packet.tlv(0x04, bytes([0x47]))
    + packet.tlv(0x05, bytes([0x01]))
    + packet.tlv(0x06, bytes([0x00]))
    + packet.tlv(0x13, bytes([0xF0]))
    + packet.tlv(0x0F, SN.encode())
)
frame = packet.build_frame(0x0A, payload)

print("1) 用实机帧还原并解析")
check("帧长 72 字节（与实机一致）", len(frame) == 72, f"{len(frame)}B")
check("帧头 AA", frame[0] == 0xAA)
parsed = packet.parse_frame(frame)
check("parse_frame 取到 cmd=0x0A", parsed is not None and parsed[0] == 0x0A)

info = device.parse_status(frame)
check("解析出 DeviceInfo", info is not None)
check("cmd 记录为 0x0a", info.cmd == 0x0A, f"0x{info.cmd:02x}")
check("序列号被识别", info.serial == SN, str(info.serial))
check("TLV 全部收齐（9 个）", len(info.fields) == 9, str(len(info.fields)))
check("tag 0x01 = 23", int.from_bytes(info.fields[0x01], "little") == 23)
check("tag 0x04 = 71", int.from_bytes(info.fields[0x04], "little") == 71)
check("tag 0x13 = 0xf0", info.fields[0x13][0] == 0xF0)

print("\n2) as_dict() 结构（给 API/网页用）")
d = info.as_dict()
print("   " + json.dumps(d, ensure_ascii=False)[:160] + " …")
check("cmd 字段是字符串", d["cmd"] == "0x0a")
check("serial 字段", d["serial"] == SN)
check("fields 以 0xNN 为键", "0x01" in d["fields"] and d["fields"]["0x01"]["int"] == 23)
check("带 note 说明", bool(d["fields"]["0x01"]["note"]))
check("ascii 字段对序列号有效", d["fields"]["0x0f"]["ascii"] == SN)

print("\n3) decode_text() 人类可读输出")
lines = device.decode_text([frame])
for line in lines:
    print("   " + line)
check("含序列号行", any("序列号" in x for x in lines))
check("含 tag 行", any("tag=0x01" in x for x in lines))

print("\n4) 坏数据不崩")
check("空帧返回 None", device.parse_status(b"") is None)
check("非帧数据返回 None", device.parse_status(b"\x01\x02\x03") is None)
check("截断帧返回 None", device.parse_status(frame[:10]) is None)
odd = packet.build_frame(0x0A, b"\x01\x02")       # TLV 不完整
check("TLV 不完整也不抛异常", device.parse_status(odd) is not None)

print("\n5) 命令帧构造")
f1 = device.status_frame()
check("status_frame = aa01000154", f1.hex() == "aa01000154", f1.hex())
f2 = device.control_frame(0x03, 1)
check("control_frame 是合法帧", f2[0] == 0xAA and f2[3] == 0x03, f2.hex())
check("control_frame 校验和正确", packet.parse_frame(f2) is not None)

print()
if fails:
    print(f"失败 {len(fails)} 项: {fails}")
    sys.exit(1)
print(f"全部通过 ✅（{passes} 项）")
