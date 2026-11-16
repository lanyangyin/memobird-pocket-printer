"""
memobird_printer/device.py — 设备信息与设置（BLE 厂商协议）

## 已实测确认（GT1，2026-11-17）

命令：

| cmd | 作用 | 回包 |
|---|---|---|
| `0x01` | 读状态（详版） | `cmd=0x01`，83B，比 0x02 多一个 `0x14`(8B) |
| `0x02` | 读状态（简版） | `cmd=0x02`，72B |
| `0x03` | **写设置**（tag=设置项, value=值） | `cmd=0x03` + `0x0E=1` 应答；随后设备主动推 `0x0A` 状态 |
| `0x04` | 打印 | 23B ack：`0x0B`=总包数 `0x0C`=包序 |
| `0x05/06/07` | 未明 | 3B payload `0d 0a 00`（像换行/走纸） |
| `0x08` | 未明 | `0x0E=1` |
| `0x09` | **读序列号** | 40B，只有 `0x0F`(32B ASCII) |
| `0x0A` | **设备主动上报状态** | 同 0x02 的 72B 帧（不是谁的应答） |

状态 TLV（`cmd 0x01/0x02/0x0A` 共用）：

| tag | 实测值 | 结论 |
|---|---|---|
| `0xFF` | `01` | 未知/固定 |
| `0x01` | `23` | **传感器值**（写 30 不生效）→ 最可能是电量 % 或温度 ℃，待充电对照确认 |
| `0x02` | `10` | **设置项**：写入 5 → 状态变 5，写回 10 → 变回 10（疑为自动关机分钟数） |
| `0x03` | `00/01` | **设置项：指示灯**（写 1 灯亮、写 0 灯灭，状态同步）✅ 因果已验证 |
| `0x04` | `80/81` | **传感器值**（自然波动 ±1；写 30 不生效）→ 疑为电池电压档位 |
| `0x05` | `01` | 传感器/状态位（只读） |
| `0x06` | `00` | 传感器/状态位（只读） |
| `0x0F` | 32B ASCII | **序列号**，实测 `636404963750000000` |
| `0x13` | `F0` | 标志位（bitfield） |
| `0x14` | 8B | 仅 `cmd 0x01` 有；曾读到 `40 12`(=4672)，后变 0 |

## 只读、可写、别碰

* 读：`0x01` 状态、`0x09` 序列号 → 完全安全
* 写：`0x03` 里 `tag 0x02`（时间）、`tag 0x03`（灯） → 可逆，已验证
* 未明：`0x05/0x06/0x07/0x08` —— 别在真机上乱发，可能有走纸/蜂鸣等副作用
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from . import packet

CMD_STATUS_DETAIL = 0x01
CMD_STATUS = 0x02
CMD_SETTING = 0x03
CMD_PRINT = 0x04
CMD_SERIAL = 0x09
CMD_STATUS_PUSH = 0x0A


@dataclass(frozen=True)
class Tag:
    name: str
    label: str
    kind: str          # sensor | setting | info | flag | unknown
    confirmed: bool = False
    note: str = ""


#: 状态帧里的 TLV tag 语义
TAGS: dict[int, Tag] = {
    0xFF: Tag("magic", "固定 0x01", "flag", False, "每次都是 01"),
    0x01: Tag("constant_23", "恒定 23（不是温度也不是电量）", "unknown", False,
              "实测：充电/打满黑页/捂热电池/写入 30 全都不变 → 更像固件常量或永不更新的假电量"),
    0x02: Tag("auto_off_minutes", "自动关机时间（分钟）", "setting", False,
              "写入即生效，状态同步；默认 10"),
    0x03: Tag("led", "指示灯", "setting", True,
              "写 1 亮 / 0 灭，状态同步 —— 因果已用肉眼验证"),
    0x04: Tag("voltage_step", "电压类读数（0.05V/LSB?）", "sensor", False,
              "会随负载变：打黑页 81→80，之后自己回来；写入无效"),
    0x05: Tag("flag_05", "状态位", "sensor", False, "恒为 1（未观察到变化）"),
    0x06: Tag("paper_out", "缺纸", "sensor", True,
              "双向验证：00:24:39 抽纸 0→1（灯变红），00:28:57 放回 1→0"),
    0x0F: Tag("serial", "序列号", "info", True, "32 字节 ASCII，尾随 \\0"),
    0x13: Tag("flags_13", "标志位", "flag", False, "0xF0 = 1111 0000"),
    0x14: Tag("counter_14", "8 字节计数?", "sensor", False,
              "仅 cmd 0x01 回包含；读到过 4672 后归零"),
}

#: 可写的设置项（cmd 0x03）：tag → (说明, 取值范围)
SETTINGS: dict[int, tuple[str, tuple[int, int]]] = {
    0x02: ("自动关机时间（分钟，待行为验证）", (1, 60)),
    0x03: ("指示灯开关", (0, 1)),
}


@dataclass
class DeviceInfo:
    cmd: int = -1
    serial: str | None = None
    fields: dict[int, bytes] = field(default_factory=dict)
    raw: bytes = b""

    def value(self, tag: int) -> int | None:
        v = self.fields.get(tag)
        return int.from_bytes(v, "little") if v is not None and len(v) <= 8 else None

    def as_dict(self) -> dict:
        out: dict = {"cmd": f"0x{self.cmd:02x}", "serial": self.serial, "fields": {}}
        for tag, val in sorted(self.fields.items()):
            meta = TAGS.get(tag)
            out["fields"][f"0x{tag:02x}"] = {
                "name": meta.name if meta else "?",
                "label": meta.label if meta else "未知",
                "kind": meta.kind if meta else "unknown",
                "confirmed": bool(meta and meta.confirmed),
                "hex": val.hex(),
                "int": int.from_bytes(val, "little") if len(val) <= 8 else None,
                "ascii": val.decode("ascii", "replace")
                if val and all(32 <= b < 127 for b in val) else None,
                "note": meta.note if meta else "",
            }
        return out


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def parse_status(frame: bytes) -> DeviceInfo | None:
    parsed = packet.parse_frame(frame)
    if not parsed:
        return None
    cmd, payload = parsed
    info = DeviceInfo(cmd=cmd, raw=frame)
    info.fields = packet.parse_tlv(payload)
    sn = info.fields.get(0x0F)
    if sn and all(32 <= b < 127 or b == 0 for b in sn):
        info.serial = sn.decode("ascii", "replace").rstrip("\x00") or None
    return info


def paper_out(info: "DeviceInfo | None") -> bool | None:
    """缺纸标志（tag 0x06）：True=缺纸，False=有纸，None=读不到。

    实机验证：有纸 0，抽出热敏纸 1（同时状态灯变红）。
    """
    if info is None:
        return None
    v = info.value(0x06)
    return None if v is None else bool(v)


def decode_text(frames: list[bytes]) -> list[str]:
    """回包 → 人类可读行（CLI/网页共用）"""
    lines: list[str] = []
    for f in frames:
        info = parse_status(f)
        if not info:
            lines.append(f"[无法解析] {f.hex(' ')}")
            continue
        lines.append(f"cmd=0x{info.cmd:02x}  {len(f)} 字节")
        if info.serial:
            lines.append(f"  序列号         : {info.serial}")
        for tag, val in sorted(info.fields.items()):
            meta = TAGS.get(tag)
            label = meta.label if meta else "未知"
            name = meta.name if meta else "?"
            if tag == 0x0F:
                continue
            n = int.from_bytes(val, "little") if len(val) <= 8 else None
            shown = val.decode("ascii", "replace") if val and all(32 <= b < 127 for b in val) else val.hex()
            tail = f"={n}" if n is not None and len(val) <= 8 else shown
            flag = " ✓" if meta and meta.confirmed else ""
            lines.append(f"  0x{tag:02x} {label:<18} {tail:<12} ({name}){flag}")
    return lines


# --------------------------------------------------------------------------- #
# 命令
# --------------------------------------------------------------------------- #
def status_frame(detail: bool = True) -> bytes:
    return packet.build_frame(CMD_STATUS_DETAIL if detail else CMD_STATUS)


def serial_frame() -> bytes:
    return packet.build_frame(CMD_SERIAL)


def setting_frame(tag: int, value: int) -> bytes:
    if tag not in SETTINGS:
        raise ValueError(f"tag 0x{tag:02x} 不在已验证的设置项里（只支持 {[hex(t) for t in SETTINGS]}）")
    lo, hi = SETTINGS[tag][1]
    if not lo <= value <= hi:
        raise ValueError(f"tag 0x{tag:02x} 取值范围 {lo}..{hi}，收到 {value}")
    return packet.build_frame(CMD_SETTING, packet.tlv(tag, bytes([value & 0xFF])))


# --------------------------------------------------------------------------- #
# 异步封装（需要 BlePrinter / 任意有 transact 的对象）
# --------------------------------------------------------------------------- #
async def read_info(link, *, detail: bool = True, wait: float = 1.5) -> list[DeviceInfo]:
    frames = await link.transact(status_frame(detail), wait=wait)
    return [i for i in (parse_status(f) for f in frames) if i and i.cmd in (CMD_STATUS_DETAIL, CMD_STATUS)]


async def read_serial(link, *, wait: float = 1.2) -> str | None:
    frames = await link.transact(serial_frame(), wait=wait)
    for f in frames:
        info = parse_status(f)
        if info and info.serial:
            return info.serial
    return None


async def set_setting(link, tag: int, value: int, *, wait: float = 1.0) -> dict[int, int]:
    """写一个设置项并读回状态，返回状态里的整数值字典"""
    await link.transact(setting_frame(tag, value), wait=wait)
    infos = await read_info(link, detail=False, wait=wait)
    if not infos:
        return {}
    info = infos[-1]
    return {t: info.value(t) for t in info.fields if info.value(t) is not None}
