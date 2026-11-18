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
                 chunk: int = 180, batch: int = 1, window: int = 1,
                 connect_retries: int = 4, connect_retry_delay: float = 1.5):
        self.address = address
        self.write_uuid = write_uuid
        self.notify_uuid = notify_uuid
        self.settle = settle
        self.timeout = timeout
        self.echo = echo
        self.chunk = max(20, int(chunk))
        self.connect_retries = max(1, int(connect_retries))
        self.connect_retry_delay = max(0.0, float(connect_retry_delay))
        self.batch = max(1, int(batch))     # 并发写入数（>1 提速，可能丢包）
        self.window = max(1, int(window))   # 流控窗口（1=逐帧等 ack，最稳）     # 每次 GATT 写入的字节数
        self._client = None
        self._rx = bytearray()          # 通知分片的接收缓冲
        self._notifies: list[bytes] = []   # 已重组成完整帧
        self._chunks: list[bytes] = []     # 原始通知分片（排查用）

    # ------------------------------------------------------------------ #
    async def __aenter__(self):
        from bleak import BleakClient

        # 打印机闲着就睡，直接连经常 "not found" —— 自动重试若干次
        attempts = max(1, int(self.connect_retries))
        last = None
        for i in range(attempts):
            self._client = BleakClient(self.address, timeout=self.timeout)
            try:
                await self._client.connect()
                last = None
                break
            except Exception as exc:                       # noqa: BLE001
                last = exc
                if i + 1 < attempts:
                    await asyncio.sleep(self.connect_retry_delay)
        if last is not None:
            raise last
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
        for i in range(0, len(data), step):
            piece = data[i:i + step]
            try:
                await self._client.write_gatt_char(self.write_uuid, piece, response=False)
            except Exception:
                await self._client.write_gatt_char(self.write_uuid, piece, response=True)
            if self.settle:
                await asyncio.sleep(self.settle)

    # ------------------------------------------------------------------ #
    # 底层：GATT 读写 / 任意帧 / 通知监听
    # ------------------------------------------------------------------ #
    async def list_gatt(self) -> list[str]:
        """列出所有服务与特征值（含属性）"""
        out = []
        for svc in self._client.services:
            out.append(f"[service] {svc.uuid}  {svc.description}")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                out.append(f"    [char] {ch.uuid}  ({props})")
        return out

    async def read_char(self, uuid: str) -> bytes:
        """读任意特征值"""
        return bytes(await self._client.read_gatt_char(uuid))

    async def write_hex(self, uuid: str, data: bytes, response: bool | None = None) -> None:
        """往任意特征值写原始字节（response=None 时按属性自动选）"""
        if response is None:
            try:
                await self._client.write_gatt_char(uuid, data, response=False)
            except Exception:
                await self._client.write_gatt_char(uuid, data, response=True)
        else:
            await self._client.write_gatt_char(uuid, data, response=response)

    async def send_hex(self, hex_str: str) -> list[bytes]:
        """发一串十六进制帧（空格可有可无），返回回包"""
        raw = bytes.fromhex(hex_str.replace(" ", "").replace("\n", ""))
        return await self.transact(raw, wait=1.0, retries=1)

    async def watch(self, seconds: float = 10.0) -> list[bytes]:
        """只订阅、不发送，监听 seconds 秒内的所有通知帧"""
        self._notifies.clear()
        self._rx.clear()
        await asyncio.sleep(seconds)
        return list(self._notifies)

    async def disconnect(self) -> None:
        """显式断开（主动释放设备，让别的 App / 机器能连）"""
        await self.__aexit__()

    @property
    def is_connected(self) -> bool:
        try:
            return bool(self._client and self._client.is_connected)
        except Exception:                                  # noqa: BLE001
            return False

    async def reconnect(self) -> None:
        """打印任务结束后固件常主动断开 —— 需要时重新连上"""
        try:
            await self.__aexit__()
        except Exception:                                  # noqa: BLE001
            pass
        await self.__aenter__()

    async def wait_last_ack(self, total: int, timeout: float = 3.0) -> bool:
        """等固件 ack 到第 total 帧（cmd 0x04 ack 里 `0x0C` 是包序）。

        为什么要等：提交帧发得太早时，打印机还没收完最后一帧，
        结果就是**只打出一半**（实测二维码只出了一半，另一半空着）。
        """
        loop = asyncio.get_event_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            for f in list(self._notifies):
                parsed = packet.parse_frame(f)
                if not parsed or parsed[0] != packet.CMD_PRINT:
                    continue
                tlv = packet.parse_tlv(parsed[1])
                idx = int.from_bytes(tlv.get(0x0C, b"\0\0"), "little")
                if idx >= total:
                    return True
            await asyncio.sleep(0.05)
        return False

    async def wait_ack_at(self, index: int, timeout: float = 2.0) -> bool:
        """等固件 ack 到第 index 帧（1-based）。"""
        loop = asyncio.get_event_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            for f in list(self._notifies):
                parsed = packet.parse_frame(f)
                if not parsed or parsed[0] != packet.CMD_PRINT:
                    continue
                tlv = packet.parse_tlv(parsed[1])
                if int.from_bytes(tlv.get(0x0C, b"\0\0"), "little") >= index:
                    return True
            await asyncio.sleep(0.02)
        return False

    async def send_frames(self, frames: Iterable[bytes], *, preheat: bool = False,
                          inter_frame: float = 0.05, wait_ack: bool = False,
                          flow_control: bool = False) -> None:
        """发送打印帧。

        flow_control=True：**每帧都等固件 ack 了再发下一帧**。
        实测不加流控时，我们一口气推 24KB，固件缓冲装不下会丢帧，
        打出来的图会被"压缩"（20mm 到 50mm 之间只剩 5mm）。
        """
        frames = list(frames)
        if preheat:
            await self.write(packet.preheat_frames())
            await asyncio.sleep(0.1)
        for i, f in enumerate(frames, 1):
            await self.write(f)
            if flow_control:
                # 窗口流控：只等"窗口之外"的那一帧。window=1 即逐帧等 ack（最稳）。
                behind = i - self.window + 1
                if behind >= 1:
                    await self.wait_ack_at(behind, timeout=2.5)
            elif inter_frame:
                await asyncio.sleep(inter_frame)
        if wait_ack and not flow_control:
            # 等最后一帧被 ack 再发终结帧，否则打印会被截断
            await self.wait_last_ack(len(frames))

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
                              terminator: str = "status", feed_lines: int = 0) -> None:
        """打印 1bpp 裸位图。

        图片帧本身没有"结束标记"，实测不补一帧固件不会真正出纸。
        终结帧三选一：

        * "commit" —— 发 cmd 0x08 提交帧（**默认**）：固件把数据打出来，且不驱动电机
        * "status" —— 发一条状态查询：也能结束任务，但实测会多走约 7mm
        * "feed"   —— 发 N 个换行（会送出 N 行空白，N=3 约 12mm）
        * "none"   —— 不发：小图能打，**大图会中途断**（实测 23 帧只出第一根刻度）
        """
        job = packet.build_bitmap_job(raw)
        await self.send_frames(job.frames, preheat=preheat, wait_ack=True)
        if terminator == "feed":
            await asyncio.sleep(0.3)
            await self.send_frames(packet.feed_job(feed_lines).frames, preheat=False)
        elif terminator == "commit":
            await asyncio.sleep(0.2)
            await self.transact(packet.commit_frame(), wait=0.6, retries=1)
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
