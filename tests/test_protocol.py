"""
离线自测：不需要打印机 / 网络。直接跑 `python tests/test_protocol.py`。

覆盖：
  1. 蓝牙帧 = 文档实测报文（逐字节）
  2. 局域网 JSON = 文档实测报文（字段与取值逐项）
  3. 云端 printcontent 的 GBK+base64 编码（含文档样例）
  4. BMP 用标准解码器回读逐像素一致
"""
import base64
import io
import json
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from memobird_printer import packet
from memobird_printer.image import dither_to_raw, prepare, raw_to_bmp, raw_to_image

fails = []


def check(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}{('  ' + detail) if detail else ''}")
    if not cond:
        fails.append(name)


# --------------------------------------------------------------------------- #
print("1) 蓝牙帧")
check("LED 开 AA0500030301000149",
      packet.build_frame(0x03, packet.tlv(0x03, b"\x01")).hex() == "aa0500030301000149")
check("读状态 AA01000154",
      packet.build_frame(0x01).hex() == "aa01000154")
p3 = packet.tlv(0x0B, struct.pack("<H", 5)) + packet.tlv(0x0C, struct.pack("<H", 1)) + packet.tlv(0x0A, struct.pack("<H", 0x29))
check("打印头帧 AA1000040B020005000C020001000A02002900EC",
      packet.build_frame(0x04, p3).hex() == "aa1000040b020005000c020001000a02002900ec")

# TLV 往返
payload = packet.tlv(0x07, "咕咕机".encode("gbk")) + packet.tlv(0x11, b"\x01")
tlvs = packet.parse_tlv(payload)
check("TLV 往返（GBK 文本）", tlvs.get(0x07) is not None and tlvs[0x07].decode("gbk") == "咕咕机")
check("TLV 往返（样式位）", tlvs.get(0x11) == b"\x01")

# 分帧
raw = bytes(range(256)) * 10  # 2560 B
job = packet.build_bitmap_job(raw)
check("位图分帧数量 = ceil(2560/1024)", job.chunks == 3, f"chunks={job.chunks}")
check("每帧 <= 1024+30 字节", all(len(f) <= 1024 + 30 for f in job.frames))
nums = [struct.unpack("<H", packet.parse_tlv(f[4:len(f) - 1])[0x0C])[0] for f in job.frames]
check("包序号从 1 递增", nums == [1, 2, 3], str(nums))

# --------------------------------------------------------------------------- #
print("\n2) 局域网 JSON")
from memobird_printer.lan import LanPrinter

captured = {}


def fake_request(self, data=None, method="GET"):
    captured["data"] = data
    captured["method"] = method
    return {"command": 3, "result": 0}


LanPrinter._request = fake_request
p = LanPrinter("127.0.0.1")
p.print_text("Hello")

d = captured["data"]
expected_fields = {
    "encryptFlag": 0, "hasHead": 0, "hasSignature": 0, "hasTail": 0,
    "isFromDirectPrint": False, "msgType": 1, "pkgCount": 1, "pkgNo": 1,
    "priority": 0, "result": 0, "scripType": 3, "command": 3,
}
check("顶层固定字段全部匹配", all(d.get(k) == v for k, v in expected_fields.items()),
      json.dumps({k: d.get(k) for k in expected_fields}, ensure_ascii=False))
item = d["content"]["textList"][0]
check("item.printType == 1 (文本)", item["printType"] == 1)
check("item.encodeType == 0", item["encodeType"] == 0)
check("basetext 是 base64(GBK)", base64.b64decode(item["basetext"]).decode("gbk") == "Hello\n")
check("printID 是整数且非 0", isinstance(d["printID"], int) and d["printID"] != 0, str(d["printID"]))

p.print_image(b"BMfake")
d2 = captured["data"]
check("图片 printType == 5 且 basetext 回读一致",
      d2["content"]["textList"][0]["printType"] == 5
      and base64.b64decode(d2["content"]["textList"][0]["basetext"]) == b"BMfake")

# --------------------------------------------------------------------------- #
print("\n3) 云端 printcontent 编码")
from memobird_printer.cloud import CloudPrinter

cp = CloudPrinter("ak_test", "9d15e1b2671043ee", 123)
calls = {}


def fake_get(self, path, params):
    calls[path] = params
    return {"result": 0}


CloudPrinter._get = fake_get
cp.print_text("你好")
tc = calls["/home/printpaper"]["printcontent"]
check("中文按 GBK 编码", base64.b64decode(tc[2:]).decode("gbk") == "你好\n", tc)
check("前缀是 T:", tc.startswith("T:"))
check("文档样例 d2VsY29tZSB0byB5b3U= -> welcome to you",
      base64.b64decode("d2VsY29tZSB0byB5b3U=").decode() == "welcome to you")
check("参数名 userID / memobirdID / ak / timestamp 齐全",
      {"ak", "timestamp", "printcontent", "memobirdID", "userID"} <= set(calls["/home/printpaper"]))
cp.print_parts("T:aGk=", "P:Qk0=")
check("多段用 | 连接", calls["/home/printpaper"]["printcontent"] == "T:aGk=|P:Qk0=",
      calls["/home/printpaper"]["printcontent"])

# --------------------------------------------------------------------------- #
print("\n4) BMP 回读")
img = prepare("咕咕机 BMP 校验 ABC 123")
w, h, mono = dither_to_raw(img, "floyd")
bmp = raw_to_bmp(w, h, mono, top_down=True)
back = Image.open(io.BytesIO(bmp)).convert("1")
check("BMP 尺寸一致", back.size == (w, h), str(back.size))
check("biHeight 为负（top-down）", struct.unpack("<i", bmp[22:26])[0] == -h)
px = back.load()
rb = (w + 7) // 8
diff = sum(
    1
    for y in range(h)
    for x in range(w)
    if (1 if mono[y * rb + (x >> 3)] & (0x80 >> (x & 7)) else 0) != (0 if px[x, y] else 1)
)
check("逐像素一致", diff == 0, f"diff={diff}")
check("宽度 = 384", w == 384, str(w))
check("裸位图行字节 = 48", rb == 48, str(rb))
check("raw_to_image 可还原", raw_to_image(w, h, mono).size == (w, h))

# --------------------------------------------------------------------------- #
print()
if fails:
    print(f"失败 {len(fails)} 项: {fails}")
    sys.exit(1)
print("全部通过 ✅")
