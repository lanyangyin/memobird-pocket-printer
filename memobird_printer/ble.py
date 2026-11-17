"""
memobird/ble.py — 蓝牙后端（BLE GATT 与经典蓝牙 SPP 两种物理链路）

BLE（GT1 实测、G4 同类）：
    service 0000ff00-0000-1000-8000-00805f9b34fb
    手机 → 打印机  write : 0000ff02-0000-1000-8000-00805f9b34fb
    打印机 → 手机  notify: 0000ff01-0000-1000-8000-00805f9b34fb
    （同时存在 0000ff80 / 0000fee7 / 49535343-... (ISSC 透传) / 0000180a）
    GT1 无配对、无身份校验：扫到就能连、能打。

经典蓝牙 SPP：GT1 也暴露 SPP（RFCOMM ch1）；Windows 上配对后会生成 COM 口，
    用 pyserial 打开即可（波特率无所谓，是虚拟串口）。

帧格式见 packet.py；发送要点：
  * 每帧长度受 MTU 限制，BLE 上按 MTU-3 切片；
  * 位图多包要**连发不等逐包 ACK**，逐包等会触发 3s 超时导致不出纸。
"""
from __future__ import annotations

import asyncio
import time
from typing import Iterable

from . import packet

SVC_FF00 = "0000ff00-0000-1000-8000-00805f9b34fb"
CHR_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb"
CHR_NOTIFY = "0000ff01-0000-1000-8000-00805f9b34fb"

NAME_HINTS = ("memobird", "gugu", "gt1", "printer", "口袋", "咕咕", "yd", "youdao")


def _is_candidate(name: str | None, service_uuids: Iterable[str] | None = None) -> bool:
    low = (name or "").lower()
    if any(h in low for h in NAME_HINTS):
        return True
    if service_uuids:
        uuids = [u.lower() for u in service_uuids]
        return any(SVC_FF00 in u or "0000ff00" in u for u in uuids)
    return False


# --------------------------------------------------------------------------- #
# BLE
# --------------------------------------------------------------------------- #
class BlePrinter:
    backend = "ble"

    def __init__(self, address: str, *, write_uuid: str = CHR_WRITE, notify_uuid: str = CHR_NOTIFY,
                 settle: float = 0.02, timeout: float = 15.0, echo: bool = True,
                 chunk: int = 180, batch: int = 1):
        self.address = address
        self.write_uuid = write_uuid
        self.notify_uuid = notify_uuid
        self.settle = settle
        self.timeout = timeout
        self.echo = echo
        self.chunk = max(20, int(chunk))     # 每次 GATT 写入的字节数
        self.batch = max(1, int(batch))      # 并发写入数：>1 时不等上一片写完，显著提速
        self._client = None
        self._rx = bytearray()          # 通知分片的接收缓冲
        self._notifies: list[bytes] = []   # 已重组成完整帧
        self._chunks: list[bytes] = []     # 原始通知分片（排查用）

    # ------------------------------------------------------------------ #
    async def __aenter__(self):
        from bleak import BleakClient

        self._client = BleakClient(self.address, timeout=self.timeout)
        await self._client.connect()
        self._notifies.clear()
        self._rx.clear()
        self._chunks.clear()
        try:
            await self._client.start_notify(self.notify_uuid, self._on_notify)
            await asyncio.sleep(0.3)          # 让订阅稳定，随后清掉残留分片
            self._notifies.clear()
            self._rx.clear()
            self._chunks.clear()
        except Exception:  # notify 不是所有固件都必填
            pass
        return self

    async def __aexit__(self, *exc):
        if self._client is not None:
            try:
                await self._client.stop_notify(self.notify_uuid)
            except Exception:
                pass
            await self._client.disconnect()

    def _on_notify(self, _sender, data: bytearray) -> None:
        """BLE 通知可能把一个长帧拆成多个 20 字节分片 —— 这里按 AA/LEN 重组。"""
        payload = bytes(data)
        self._chunks.append(payload)
        self._rx.extend(payload)

        while len(self._rx) >= 5:
            if self._rx[0] != 0xAA:                 # 失步，丢一个字节重新对齐
                del self._rx[0]
                continue
            length = self._rx[1] | (self._rx[2] << 8)
            total = 3 + length + 1
            if len(self._rx) < total:
                break                               # 还没收全，等下一片
            frame = bytes(self._rx[:total])
            del self._rx[:total]
            self._notifies.append(frame)
            if self.echo:
                print(f"[notify] {frame.hex(' ')}")

    # ------------------------------------------------------------------ #
    async def write(self, data: bytes) -> None:
        """按 MTU 切片写入（write-without-response 更快，失败回退 write-with-response）。"""
        assert self._client is not None
        step = self.chunk
        pieces = [data[i:i + step] for i in range(0, len(data), step)]

        async def send_one(piece: bytes):
            try:
                await self._client.write_gatt_char(self.write_uuid, piece, response=False)
            except Exception:
                await self._client.write_gatt_char(self.write_uuid, piece, response=True)

        if self.batch <= 1:
            for piece in pieces:
                await send_one(piece)
                if self.settle:
                    await asyncio.sleep(self.settle)
        else:
            # 流水线：一批 batch 个写入并发提交，避免每次 50ms 的往返开销累积
            for i in range(0, len(pieces), self.batch):
                await asyncio.gather(*(send_one(p) for p in pieces[i:i + self.batch]))
                if self.settle:
                    await asyncio.sleep(self.settle)

    async def send_frames(self, frames: Iterable[bytes], *, preheat: bool = False,
                          inter_frame: float = 0.05) -> None:
        if preheat:
            await self.write(packet.preheat_frames())
            await asyncio.sleep(0.1)
        for f in frames:
            await self.write(f)
            if inter_frame:
                await asyncio.sleep(inter_frame)

    # ------------------------------------------------------------------ #
    async def status(self) -> bytes:
        await self.write(packet.status_request())
        await asyncio.sleep(0.5)
        return b""

    async def transact(self, frame: bytes, wait: float = 1.2, retries: int = 2) -> list[bytes]:
        """
        发一帧并收集完整回包帧（读设备信息/试探命令用）。

        两个坑（Windows + GT1 实测）：
          1. 刚订阅 notify 时会先收到**上一次连接残留的分片** → 每次发送前清空缓冲；
          2. 偶发丢应答 → 自动重试。
        """
        for attempt in range(max(1, retries)):
            self._notifies.clear()
            self._rx.clear()
            self._chunks.clear()
            await self.write(frame)
            await asyncio.sleep(wait + 0.3 * attempt)
            if self._notifies:
                return list(self._notifies)
        return []

    async def read_device_info(self, wait: float = 1.2):
        """cmd 0x01 → 解析成 DeviceInfo（见 device.py）"""
        from . import device

        frames = await self.transact(device.status_frame(), wait=wait)
        infos = [i for i in (device.parse_status(f) for f in frames) if i]
        return infos, frames

    async def sweep(self, cmds: range | list[int], wait: float = 0.8) -> dict[int, list[bytes]]:
        """逐个发空命令，返回 {cmd: [回包]}。只发无 payload 的命令，不会改配置。"""
        out: dict[int, list[bytes]] = {}
        for cmd in (cmds if isinstance(cmds, list) else list(cmds)):
            out[cmd] = await self.transact(packet.build_frame(cmd), wait=wait)
            await asyncio.sleep(0.2)
        return out

    async def print_text(self, text: str, *, encoding: str = "gbk") -> None:
        if not text.endswith("\n"):
            text += "\n"
        job = packet.build_text_job(text, encoding=encoding)
        await self.send_frames(job.frames, preheat=True)

    async def print_raw_image(self, raw: bytes, *, preheat: bool = True,
                              terminator: str = "feed", feed_lines: int = 3) -> None:
        """打印 1bpp 裸位图。

        图片帧本身没有"结束标记"，实测不补一帧固件不会真正出纸。
        终结帧三选一：

        * "feed"   —— 发 N 个换行（会送出 N 行空白，N=3 约 12mm）
        * "status" —— 发一条状态查询（不驱动电机 ⇒ 零走纸）
        * "none"   —— 不发（实测多数固件不出纸）
        """
        job = packet.build_bitmap_job(raw)
        await self.send_frames(job.frames, preheat=preheat)
        if terminator == "feed":
            await asyncio.sleep(0.3)
            await self.send_frames(packet.feed_job(feed_lines).frames, preheat=False)
        elif terminator == "status":
            await asyncio.sleep(0.15)
            await self.transact(packet.build_frame(packet.CMD_STATUS), wait=0.4, retries=1)


async def scan(timeout: float = 8.0, *, all_devices: bool = False) -> list[dict]:
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=timeout)
    out = []
    for d in found:
        uuids = getattr(d, "metadata", {}).get("uuids", []) or []
        if all_devices or _is_candidate(d.name, uuids):
            out.append({"address": d.address, "name": d.name, "rssi": getattr(d, "rssi", None), "uuids": uuids})
    return out


async def gatt_dump(address: str, timeout: float = 15.0) -> list[dict]:
    """把设备的 GATT 表打印出来 —— 型号不确定时用它找可写/可通知特征值。"""
    from bleak import BleakClient

    rows = []
    async with BleakClient(address, timeout=timeout) as client:
        for svc in client.services:
            rows.append({"type": "service", "uuid": svc.uuid, "handle": svc.handle})
            for ch in svc.characteristics:
                rows.append({
                    "type": "characteristic", "uuid": ch.uuid, "handle": ch.handle,
                    "props": list(ch.properties),
                })
    return rows


# --------------------------------------------------------------------------- #
# 经典蓝牙 SPP（Windows 上表现为 COM 口）
# --------------------------------------------------------------------------- #
class SppPrinter:
    backend = "spp"

    def __init__(self, port: str, *, baudrate: int = 115200, settle: float = 0.03):
        self.port = port
        self.baudrate = baudrate
        self.settle = settle
        self._ser = None

    def __enter__(self):
        import serial  # pyserial

        self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
        return self

    def __exit__(self, *exc):
        if self._ser is not None:
            self._ser.close()

    def write(self, data: bytes) -> None:
        assert self._ser is not None
        self._ser.write(data)
        self._ser.flush()
        if self.settle:
            time.sleep(self.settle)

    def send_frames(self, frames: Iterable[bytes], *, preheat: bool = False) -> None:
        if preheat:
            self.write(packet.preheat_frames())
        for f in frames:
            self.write(f)

    def print_text(self, text: str, *, encoding: str = "gbk") -> None:
        if not text.endswith("\n"):
            text += "\n"
        self.send_frames(packet.build_text_job(text, encoding=encoding).frames, preheat=True)

    def print_raw_image(self, raw: bytes) -> None:
        self.send_frames(packet.build_bitmap_job(raw).frames, preheat=True)
