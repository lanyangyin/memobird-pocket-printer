"""
memobird/packet.py — 咕咕机/有道口袋打印机 蓝牙帧 + TLV 编解码

帧结构（BLE notify 与经典蓝牙 SPP 同一套）:

    AA | LEN(2B, little-endian) | CMD(1B) | PAYLOAD(TLV...) | CHECKSUM(1B)

    LEN      = 1(cmd) + len(payload)
    CHECKSUM = (0x56 - (LEN_lo + LEN_hi + CMD + sum(payload))) & 0xFF

校验和与「(256 - sum(AA + body)) & 0xFF」代数等价（因 0xAA + 0x56 == 0x100）。

TLV = TAG(1B) + LEN(2B little-endian) + VALUE

常用 TAG:
    0x07  文本(GBK)
    0x08  位图分片(<=1024B)
    0x0A  数据总长
    0x0B  总包数
    0x0C  包序号(从 1 开始)
    0x0D / 0x10 / 0x11 / 0x12  样式位（字号/加粗/下划线等）

常用 CMD:
    0x01  查询状态（电量/版本/SN）
    0x03  控制（指示灯、打印浓度）
    0x04  打印
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

HEADER = 0xAA
MAGIC_SUM = 0x56

CMD_STATUS = 0x01
CMD_CONTROL = 0x03
CMD_PRINT = 0x04
CMD_COMMIT = 0x08      # 提交/结束任务（实测不驱动电机，但能让固件把位图打出来）

TAG_TEXT = 0x07
TAG_BITMAP = 0x08
TAG_TOTAL_LEN = 0x0A
TAG_PKG_COUNT = 0x0B
TAG_PKG_NO = 0x0C
TAG_BOLD = 0x0D
TAG_FONT_SIZE = 0x10
TAG_UNDERLINE = 0x11
TAG_STYLE_10 = 0x10
TAG_STYLE_11 = 0x11
TAG_STYLE_12 = 0x12

MAX_CHUNK = 1024          # 单帧位图载荷上限（官方 SDK 实测值）
TEXT_CHUNK = 300          # 单帧文本载荷上限（官方 SDK 实测值）
PREHEAT = 2048            # 打印前需先发 2×1024 字节 0x00 预热


def checksum(body: bytes) -> int:
    """body = LEN(2) + CMD(1) + PAYLOAD"""
    return (MAGIC_SUM - sum(body)) & 0xFF


def commit_frame() -> bytes:
    """提交/结束当前打印任务的信号（cmd 0x08）。

    实测：**不驱动电机**，但能让固件把已收到的位图真正打出来。
    图片帧本身没有结束标记，用它收尾既能完整打印、又不会多走纸。
    """
    return build_frame(CMD_COMMIT)


def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    body = struct.pack("<H", len(payload) + 1) + bytes([cmd]) + payload
    return bytes([HEADER]) + body + bytes([checksum(body)])


def tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + struct.pack("<H", len(value)) + value


def parse_tlv(payload: bytes) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    i = 0
    while i + 3 <= len(payload):
        tag = payload[i]
        (length,) = struct.unpack("<H", payload[i + 1:i + 3])
        val = payload[i + 3:i + 3 + length]
        if len(val) != length:
            break
        out[tag] = val
        i += 3 + length
    return out


def parse_frame(data: bytes) -> tuple[int, bytes] | None:
    """从一个接收缓冲区里切出一帧：返回 (cmd, payload) 或 None。"""
    if len(data) < 5 or data[0] != HEADER:
        return None
    (length,) = struct.unpack("<H", data[1:3])
    total = 3 + length + 1
    if len(data) < total:
        return None
    cmd = data[3]
    payload = data[4:3 + length]
    return cmd, payload


# --------------------------------------------------------------------------- #
# 打印任务
# --------------------------------------------------------------------------- #
@dataclass
class PrintJob:
    """一个打印任务被切成的多帧，按发送顺序排列。"""
    frames: list[bytes] = field(default_factory=list)
    total_bytes: int = 0
    chunks: int = 0


def build_text_job(
    text: str,
    *,
    encoding: str = "gbk",
    bold: bool = False,
    underline: bool = False,
    font_size: int = 0,
    chunk: int = TEXT_CHUNK,
    include_total_len: bool = False,
) -> PrintJob:
    """
    文本打印（对齐官方 SDK）：

        tag 0x0B 总包数 | 0x0C 包序号 | 0x0D 加粗 | 0x11 下划线 | 0x10 字号 | 0x07 GBK 文本

    要点：
      * 每包文本 **不超过 300 字节**（官方 SDK 值），超了要分包；
      * 字号走 **tag 0x10**，是固件档位（0/1/2…），不是像素字号；
      * 不需要 tag 0x0A。
    """
    data = text.encode(encoding, "replace")
    pieces = [data[i:i + chunk] for i in range(0, len(data), chunk)] or [b"\n"]
    count = len(pieces)
    job = PrintJob(total_bytes=len(data), chunks=count)
    for idx, piece in enumerate(pieces, start=1):
        parts = [
            tlv(TAG_PKG_COUNT, struct.pack("<H", count)),
            tlv(TAG_PKG_NO, struct.pack("<H", idx)),
            tlv(TAG_BOLD, bytes([1 if bold else 0])),
            tlv(TAG_UNDERLINE, bytes([1 if underline else 0])),
            tlv(TAG_FONT_SIZE, bytes([font_size & 0xFF])),
        ]
        if include_total_len:
            parts.append(tlv(TAG_TOTAL_LEN, struct.pack("<H", len(data) & 0xFFFF)))
        parts.append(tlv(TAG_TEXT, piece))
        job.frames.append(build_frame(CMD_PRINT, b"".join(parts)))
    return job


def feed_job(lines: int = 3) -> PrintJob:
    """走纸：发一段纯换行的文本，让内容吐出来（官方 SDK 打图后会这么做）。"""
    return build_text_job("\n" * max(1, lines))


def build_bitmap_job(raw: bytes, *, chunk: int = MAX_CHUNK) -> PrintJob:
    """
    1bpp 裸位图（384 宽、MSB 在左、行按字节对齐）切成多帧（tag 0x08 = 裸位图）。
    发送端要**连发不等逐包 ACK**（逐包等会触发 3s 超时导致不出纸）。
    """
    return _chunked_job(raw, TAG_BITMAP, chunk)


def build_bmp_job(bmp: bytes, *, chunk: int = MAX_CHUNK) -> PrintJob:
    """
    整份 BMP 文件字节切成多帧（tag 0x08）。

    公开抓包里的位图帧载荷以 `BM` 开头，说明设备端收的是**BMP 文件**而不是裸位图；
    但不同固件/机型存在差异，所以两种都提供：
        * 先试 build_bmp_job(BMP 文件)
        * 不出图再试 build_bitmap_job(裸位图)
    """
    return _chunked_job(bmp, TAG_BITMAP, chunk)


def _chunked_job(data: bytes, tag: int, chunk: int, *, include_total_len: bool = False) -> PrintJob:
    pieces = [data[i:i + chunk] for i in range(0, len(data), chunk)] or [b""]
    count = len(pieces)
    job = PrintJob(total_bytes=len(data), chunks=count)
    for idx, piece in enumerate(pieces, start=1):
        parts = [
            tlv(TAG_PKG_COUNT, struct.pack("<H", count)),
            tlv(TAG_PKG_NO, struct.pack("<H", idx)),
        ]
        if include_total_len:
            parts.append(tlv(TAG_TOTAL_LEN, struct.pack("<H", len(data) & 0xFFFF)))
        parts.append(tlv(tag, piece))
        job.frames.append(build_frame(CMD_PRINT, b"".join(parts)))
    return job


def status_request() -> bytes:
    return build_frame(CMD_STATUS)


def control_led(on: bool = True) -> bytes:
    return build_frame(CMD_CONTROL, tlv(0x03, bytes([0x01 if on else 0x00])))


def preheat_frames() -> bytes:
    """0x00 预热数据（2×1024B），部分固件要求打印前先发。"""
    return b"\x00" * PREHEAT


# --------------------------------------------------------------------------- #
# 一站式：任意内容 → 可直接逐帧写进 GATT 的字节列表
# --------------------------------------------------------------------------- #
def job_for_text(
    text: str,
    *,
    encoding: str = "gbk",
    bold: bool = False,
    underline: bool = False,
    font_size: int = 0,
) -> PrintJob:
    if not text.endswith("\n"):
        text += "\n"
    return build_text_job(text, encoding=encoding, bold=bold, underline=underline, font_size=font_size)


def job_for_image_bytes(data: bytes, *, as_bmp_file: bool = True) -> PrintJob:
    """data 是 BMP 文件字节（as_bmp_file=True）或裸 1bpp 位图。"""
    return build_bmp_job(data) if as_bmp_file else build_bitmap_job(data)
