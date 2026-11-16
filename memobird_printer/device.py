"""
memobird_printer/device.py — 读设备信息（电量 / 版本 / 序列号 / 配置）

协议层结论（来自实机抓包 + 参考实现）：
  · `cmd 0x01`：读状态。设备回一帧 `cmd=0x0A` 的长报文，TLV 形式。
  · `cmd 0x03`：控制/配置（指示灯、打印浓度、自动关机等），具体 tag 待逐个试探。
  · `cmd 0x04`：打印。

⚠️ tag 语义目前只有部分证实（见 FIELDS），其余保留原始字节。
   实测样例（GT1，72B 回包）：

       aa 44 00 0a
       ff 01 00 01
       01 01 00 17         <- 23
       02 01 00 0a         <- 10
       03 01 00 01
       04 01 00 47         <- 71
       05 01 00 01
       06 01 00 00
       13 01 00 f0
       0f 20 00 "636404963750..."   <- 32 字节 ASCII，序列号
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import packet

CMD_STATUS = 0x01
CMD_CONTROL = 0x03
CMD_PRINT = 0x04

#: 已知/推测的 TLV tag 语义。带 "?" 的是推测，需要实机对照确认。
FIELDS: dict[int, tuple[str, str]] = {
    0x00: ("?", "未知"),
    0x01: ("battery?", "推测：电量百分比（实测见 23，与‘低电量发灰’吻合）"),
    0x02: ("value_0x02?", "推测：温度/电压/版本分量"),
    0x03: ("value_0x03?", "推测：状态位"),
    0x04: ("value_0x04?", "推测：计数/电压"),
    0x05: ("value_0x05?", "推测：状态位"),
    0x06: ("value_0x06?", "推测：状态位"),
    0x0F: ("serial", "32 字节 ASCII 序列号"),
    0x13: ("value_0x13?", "推测：标志位（实测 f0）"),
}


@dataclass
class DeviceInfo:
    """解析后的设备信息：已知字段 + 原始 TLV"""

    cmd: int = -1
    serial: str | None = None
    fields: dict[int, bytes] = field(default_factory=dict)
    raw: bytes = b""
    text: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        out: dict = {
            "cmd": f"0x{self.cmd:02x}",
            "serial": self.serial,
            "fields": {
                f"0x{tag:02x}": {
                    "name": FIELDS.get(tag, ("?", "未知"))[0],
                    "hex": val.hex(),
                    "int": int.from_bytes(val, "little") if len(val) <= 4 else None,
                    "ascii": val.decode("ascii", "replace")
                    if val and all(32 <= b < 127 for b in val) else None,
                    "note": FIELDS.get(tag, ("", ""))[1],
                }
                for tag, val in sorted(self.fields.items())
            },
        }
        if self.text:
            out["text"] = self.text
        return out


def parse_status(frame: bytes) -> DeviceInfo | None:
    """把设备回的一帧解析成 DeviceInfo。帧必须是完整帧（含 AA 与校验和）。"""
    parsed = packet.parse_frame(frame)
    if not parsed:
        return None
    cmd, payload = parsed
    info = DeviceInfo(cmd=cmd, raw=frame)
    for tag, val in packet.parse_tlv(payload).items():
        info.fields[tag] = val

    sn = info.fields.get(0x0F)
    if sn and all(32 <= b < 127 for b in sn):
        info.serial = sn.decode("ascii", "replace").rstrip("\x00")
    return info


def decode_text(frames: list[bytes]) -> list[str]:
    """把回包渲染成人类可读的行（给 CLI / 网页用）"""
    lines: list[str] = []
    for f in frames:
        info = parse_status(f)
        if not info:
            lines.append(f"[无法解析] {f.hex()}")
            continue
        lines.append(f"cmd=0x{info.cmd:02x}  {len(f)} 字节")
        if info.serial:
            lines.append(f"  序列号     : {info.serial}")
        for tag, val in sorted(info.fields.items()):
            name, note = FIELDS.get(tag, ("?", "未知"))
            n = int.from_bytes(val, "little") if len(val) <= 4 else None
            shown = val.decode("ascii", "replace") if val and all(32 <= b < 127 for b in val) else val.hex()
            lines.append(f"  tag=0x{tag:02x}  {name:<14} {shown}"
                         + (f"  (={n})" if n is not None and len(val) <= 2 else "")
                         + (f"   # {note}" if note else ""))
    return lines


# --------------------------------------------------------------------------- #
# 命令构造（配置类：需要谨慎，逐个试）
# --------------------------------------------------------------------------- #
def status_frame() -> bytes:
    return packet.build_frame(CMD_STATUS)


def control_frame(tag: int, value: int) -> bytes:
    """cmd 0x03 的控制帧：单字节 TLV。tag 语义待确认，请先在设备上小步试探。"""
    return packet.build_frame(CMD_CONTROL, packet.tlv(tag, bytes([value & 0xFF])))
