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
                 settle: float = 0.02, timeout: float = 15.0):
        self.address = address
        self.write_uuid = write_uuid
        self.notify_uuid = notify_uuid
        self.settle = settle
        self.timeout = timeout
        self._client = None

    # ------------------------------------------------------------------ #
    async def __aenter__(self):
        from bleak import BleakClient

        self._client = BleakClient(self.address, timeout=self.timeout)
        await self._client.connect()
        try:
            await self._client.start_notify(self.notify_uuid, self._on_notify)
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
        print(f"[notify] {bytes(data).hex(' ')}")

    # ------------------------------------------------------------------ #
    async def write(self, data: bytes) -> None:
        """按 MTU 切片写入（write-without-response 更快，失败回退 write-with-response）。"""
        assert self._client is not None
        mtu = getattr(self._client, "mtu_size", None) or 23
        step = max(20, mtu - 3)
        for i in range(0, len(data), step):
            chunk = data[i:i + step]
            try:
                await self._client.write_gatt_char(self.write_uuid, chunk, response=False)
            except Exception:
                await self._client.write_gatt_char(self.write_uuid, chunk, response=True)
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

    async def print_text(self, text: str, *, encoding: str = "gbk") -> None:
        if not text.endswith("\n"):
            text += "\n"
        job = packet.build_text_job(text, encoding=encoding)
        await self.send_frames(job.frames, preheat=True)

    async def print_raw_image(self, raw: bytes, *, preheat: bool = True) -> None:
        job = packet.build_bitmap_job(raw)
        await self.send_frames(job.frames, preheat=preheat)


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
