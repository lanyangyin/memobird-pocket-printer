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
| `0x02` | `10` | **打印浓度 1..10**（写 3 明显变浅）；浓度越低打印越慢，长图才打得完整 |
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
    0x02: Tag("density", "打印浓度（1..10）", "setting", True,
              "写 3 后打印明显变浅 ✅；浓度越低每行加热越久 ⇒ 打印越慢，"
              "慢速 BLE（~3KB/s）下反而能完整打完长图"),
    0x03: Tag("led", "指示灯", "setting", True,
              "写 1 亮 / 0 灭，状态同步 —— 因果已用肉眼验证"),
    0x04: Tag("battery_voltage", "电池电压（0.05V/LSB）", "sensor", True,
              "实测随充电上升(74→80)、随负载下降，是电池电压；可估算电量"),
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
    0x02: ("打印浓度 1..10", (1, 10)),
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

        # 电量（由 0x04 电压估算）
        volts = battery_voltage(self)
        if volts is not None:
            out["battery"] = {"voltage": volts, "percent": battery_percent(self),
                              "note": "由 0x04 × 0.05V 估算，±10%，负载时偏低"}
        out["paper_out"] = paper_out(self)
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



# --------------------------------------------------------------------------- #
# 电量：固件不直接给百分比，但 0x04 是电池电压（0.05 V/LSB）
# 实测：未充电 74(3.70V) → 插电充电后 79~80(3.95~4.00V) → 充电时上升、负载时下掉
# 所以只能给"由电压估算的百分比"，误差约 ±10%，负载重时会偏低。
# --------------------------------------------------------------------------- #
VOLTS_PER_LSB = 0.05

# 打印浓度默认值（0x02 = 1..10）。官方 App 默认就是 10（最深）。
DEFAULT_DENSITY = 10

# 锂电静置电压 → 剩余电量（标称曲线，非精确库仑计）
_LI_CURVE = (
    (3.30, 0), (3.40, 3), (3.50, 8), (3.60, 14), (3.70, 25),
    (3.75, 35), (3.80, 45), (3.85, 53), (3.90, 60), (3.95, 68),
    (4.00, 75), (4.05, 83), (4.10, 90), (4.15, 96), (4.20, 100),
)


def battery_voltage(info: "DeviceInfo | None") -> float | None:
    """0x04 → 伏特（0.05 V/LSB，推测值，实测变化趋势吻合锂电）"""
    v = info.value(0x04) if info else None
    return None if v is None else round(v * VOLTS_PER_LSB, 2)


def battery_percent(info: "DeviceInfo | None") -> int | None:
    """电压 → 估算电量百分比（±10%，负载时偏低）"""
    volts = battery_voltage(info)
    if volts is None:
        return None
    if volts <= _LI_CURVE[0][0]:
        return 0
    if volts >= _LI_CURVE[-1][0]:
        return 100
    for (v1, p1), (v2, p2) in zip(_LI_CURVE, _LI_CURVE[1:]):
        if v1 <= volts <= v2:
            return round(p1 + (p2 - p1) * (volts - v1) / (v2 - v1))
    return None


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
            extra = ""
            if tag == 0x04 and n is not None:
                volts = round(n * VOLTS_PER_LSB, 2)
                pct = battery_percent(info)
                extra = f"  ≈{volts}V / 约 {pct}% 电量"
            lines.append(f"  0x{tag:02x} {label:<18} {tail:<12} ({name}){flag}{extra}")
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


async def wait_for_paper(link, *, timeout: float | None = 300.0,
                        interval: float = 3.0, on_tick=None) -> bool:
    """等打印机重新装上纸。返回 True=已经有纸，False=超时/读不到。

    timeout=None 表示一直等。on_tick(seconds, missing) 可以拿来做进度提示。
    """
    import time as _time

    t0 = _time.monotonic()
    while True:
        elapsed = _time.monotonic() - t0
        try:
            infos = await read_info(link, detail=False, wait=1.0)
            missing = paper_out(infos[-1] if infos else None)
        except Exception:                                      # noqa: BLE001
            missing = None                                     # 读不到就当不知道
        if missing is False:                                   # 明确"有纸"
            return True
        if timeout is not None and elapsed >= timeout:
            return False
        if on_tick:
            try:
                on_tick(elapsed, missing)
            except Exception:                                  # noqa: BLE001
                pass
        await asyncio.sleep(interval)


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
