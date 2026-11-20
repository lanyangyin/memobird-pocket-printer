"""Dothantech P1 标签机 —— 免厂商 App 的 BLE 客户端（已在真机验证）

实测通过（2026-11-20，P1-61085930 / 28:D4:1E:9A:99:DB，固件 5.20）：

* 写数据：FF02（write without response），单片 20 字节
* 流控：FF03 通知 `01 nn` = 授予 nn 个信用额度；每写一片消耗 1 个
* 打印内容：**裸 ESC/POS**（`GS v 0` 光栅 + `ESC J` 走纸），不需要 AA/BB 帧
* AA/BB 帧只在"控制命令"时用（探测/查询），内容直接发字节流

用法：
    python p1_client.py info                       # 读型号/固件/序列号
    python p1_client.py demo                       # 打一张黑白格子测试图
    python p1_client.py print-png a.png --feed 32   # 打一张 PNG
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import weida_protocol as W  # noqa: E402

FF01 = "0000ff01-0000-1000-8000-00805f9b34fb"
FF02 = "0000ff02-0000-1000-8000-00805f9b34fb"
FF03 = "0000ff03-0000-1000-8000-00805f9b34fb"

INFO_UUIDS = {
    "厂商": "00002a29-0000-1000-8000-00805f9b34fb",
    "型号": "00002a24-0000-1000-8000-00805f9b34fb",
    "序列号": "00002a25-0000-1000-8000-00805f9b34fb",
    "固件": "00002a26-0000-1000-8000-00805f9b34fb",
    "硬件": "00002a27-0000-1000-8000-00805f9b34fb",
    "软件": "00002a28-0000-1000-8000-00805f9b34fb",
}

# 名称 → 数值（中文别名也接受）
GAP_TYPES = {
    "none": 0, "continuous": 0, "连续": 0,
    "hole": 1, "孔": 1,
    "gap": 2, "不干胶": 2, "标签": 2,
    "black": 3, "黑标": 3,
    "transparent": 4, "trans": 4, "透明": 4,
}

DEFAULT_CHUNK = 20
DEFAULT_SETTLE = 0.004


class P1Client:
    """P1 标签机 BLE 客户端（信用流控）。"""

    def __init__(self, addr: str, *, chunk: int = DEFAULT_CHUNK,
                 settle: float = DEFAULT_SETTLE, echo: bool = True):
        self.addr = addr
        self.chunk = chunk
        self.settle = settle
        self.echo = echo
        self.client = None
        self.credits = 0
        self.sent_bytes = 0
        self.messages: list[tuple[str, str]] = []
        self.rxq: list[tuple[int, bytes]] = []
        self.push_status: list[dict] = []
        self._waiter: asyncio.Future | None = None
        self._cond = asyncio.Condition()
        self._loop = None

    # ---------------- 生命周期 ----------------
    async def __aenter__(self):
        from bleak import BleakClient

        self._loop = asyncio.get_running_loop()
        for attempt in range(4):
            try:
                self.client = BleakClient(self.addr, timeout=30)
                await self.client.connect()
                break
            except Exception as exc:
                if attempt == 3:
                    raise OSError(
                        f"连不上 {self.addr}（{type(exc).__name__}）。"
                        f"打印机可能需要重启：断电再开机，然后重试") from exc
                if self.echo:
                    print(f"    连接失败（{attempt + 1}/4），2 秒后重试…", flush=True)
                await asyncio.sleep(2.0)
        # ---- 自动识别通道 ----
        uuids = set()
        self.chunk = DEFAULT_CHUNK
        for svc in self.client.services:
            for ch in svc.characteristics:
                uuids.add(ch.uuid.lower())
        self.write_uuid, self.notify_uuid, self.credit_mode = self._pick_channels(uuids)

        if self.credit_mode:
            # P1：FF03 给信用额度
            await self.client.start_notify(self.crf_uuid, self._on_credit)
        try:
            await self.client.start_notify(self.notify_uuid, self._on_notify)
        except Exception:                            # noqa: BLE001
            pass

        # MTU 决定分片（P2 的透传通常能到 180+）
        try:
            mtu = self.client.mtu_size
            if mtu and mtu > 23:
                self.chunk = max(20, mtu - 3)
        except Exception:                            # noqa: BLE001
            pass
        if self.echo:
            print(f"    通道: write={self.write_uuid[:8]} notify={self.notify_uuid[:8]} "
                  f"信用={self.credit_mode} 分片={self.chunk}", flush=True)
        if not self.credit_mode:
            self.credits = 10 ** 6                   # 无流控通道：不等待
        await asyncio.sleep(1.2)                     # 等固件准备好 + 初始额度
        # 初始化：开启设置（实测必须，否则 0x88 查询无回包）
        try:
            await self.send_cmd(W.CMD_ENABLE_SETTING, b"\x7f")
            await asyncio.sleep(0.3)
        except Exception:                            # noqa: BLE001
            pass
        return self

    async def __aexit__(self, *exc):
        try:
            await self.client.disconnect()
        except Exception:                            # noqa: BLE001
            pass
        return False

    def _log(self, text: str, chan: str = "") -> None:
        self.messages.append((chan, text))
        if self.echo:
            print(f"    <- {chan} {text}", flush=True)

    # ---------------- 通道识别 ----------------
    FF00, FF01, FF02, FF03 = (f"0000ff{n:02x}-0000-1000-8000-00805f9b34fb"
                              for n in (0x00, 0x01, 0x02, 0x03))
    ISSC_NOTIFY = "49535343-1e4d-4bd9-ba61-23c647249616"
    ISSC_WRITE = "49535343-8841-43f4-a8d4-ecbe34729bb3"

    def _pick_channels(self, uuids: set[str]) -> tuple[str, str, bool]:
        """返回 (写 uuid, 通知 uuid, 是否信用模式)。"""
        if self.FF03 in uuids and self.FF02 in uuids:
            self.crf_uuid = self.FF03
            return self.FF02, self.FF01, True
        if self.ISSC_WRITE in uuids:
            self.crf_uuid = ""
            return self.ISSC_WRITE, self.ISSC_NOTIFY, False
        # 兜底：FF00 家族
        if self.FF02 in uuids:
            self.crf_uuid = self.FF03 if self.FF03 in uuids else ""
            return self.FF02, self.FF01, bool(self.crf_uuid)
        raise OSError("找不到可用的写/通知特征值")

    def _on_credit(self, _sender, data: bytearray) -> None:
        raw = bytes(data)
        self._log(raw.hex(" "), "CREDIT")
        if len(raw) >= 2 and raw[0] == 0x01:
            self._loop.create_task(self._grant(raw[1]))

    def _on_notify(self, _sender, data: bytearray) -> None:
        raw = bytes(data)
        self._log(raw.hex(" "), "RX")
        for cmd, payload in W.parse_frames(raw):
            self.rxq.append((cmd, payload))
            if cmd == W.CMD_PUSH_STATUS:
                self.push_status.append(W.decode_push(payload))
            if self._waiter is not None and not self._waiter.done():
                self._waiter.set_result((cmd, payload))

    async def _grant(self, n: int) -> None:
        async with self._cond:
            self.credits += n
            self._cond.notify_all()

    # ---------------- 发送 ----------------
    async def send(self, data: bytes, *, timeout: float = 8.0) -> bool:
        """按信用额度分片发送。"""
        for i in range(0, len(data), self.chunk):
            piece = data[i:i + self.chunk]
            deadline = time.time() + timeout
            async with self._cond:
                while self.credits <= 0 and time.time() < deadline:
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=0.3)
                    except asyncio.TimeoutError:
                        pass
                if self.credits <= 0:
                    if self.echo:
                        print(f"    ⚠ 等额度超时（已发 {self.sent_bytes} 字节）", flush=True)
                    return False
                self.credits -= 1
            try:
                await self.client.write_gatt_char(self.write_uuid, piece, response=False)
            except Exception:                        # noqa: BLE001
                await self.client.write_gatt_char(self.write_uuid, piece, response=True)
            self.sent_bytes += len(piece)
            if self.settle:
                await asyncio.sleep(self.settle)
        return True

    async def set_gap_type(self, gap: "str | int") -> bool:
        """设置标签间隙类型（0x42）。不干胶标签用 gap=2。"""
        val = GAP_TYPES.get(gap, gap) if isinstance(gap, str) else gap
        return await self.send_cmd(0x42, bytes([int(val) & 0xFF]))

    async def send_cmd(self, cmd: int, payload: bytes = b"") -> bool:
        """发一条控制命令（0x1F 帧），走同一条信用通道。"""
        return await self.send(W.frame(cmd, payload))

    async def query(self, cmd: int, payload: bytes = b"",
                    *, timeout: float = 3.0) -> tuple[int, bytes] | None:
        """发命令并等它的回包。"""
        self._waiter = asyncio.get_running_loop().create_future()
        try:
            await self.send_cmd(cmd, payload)
            return await asyncio.wait_for(self._waiter, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._waiter = None

    async def status(self) -> dict:
        """查打印状态（缺纸/开盖/过热…）。"""
        r = await self.query(W.CMD_IS_PRINTABLE)
        if not r:
            return {"ok": False, "error": "无回包"}
        return {"ok": True, **W.decode_status(r[1])}

    async def battery(self) -> dict:
        """电量（0x88 / ADCEVT_POWER），失败时退回到 0x40 推送。"""
        r = await self.query(W.CMD_REQ_ADCVALUE, bytes([W.ADCEVT_POWER]))
        if r:
            info = W.decode_adc(r[1])
            if info.get("battery_v") is not None:
                return {"ok": True, **info}
        if self.push_status:
            last = self.push_status[-1]
            if last.get("battery_v") is not None:
                return {"ok": True, **last}
        return {"ok": False, "error": "无电量数据"}

    async def head_temp(self) -> dict:
        """打印头温度（0x88 / ADCEVT_TPHTM）。"""
        r = await self.query(W.CMD_REQ_ADCVALUE, bytes([W.ADCEVT_TPHTM]))
        if not r:
            return {"ok": False, "error": "无回包"}
        info = W.decode_adc(r[1])
        return {"ok": info.get("head_temp_c") is not None, **info}

    # ---------------- 便捷操作 ----------------
    async def read_info(self) -> dict:
        """设备信息：GATT 180A + 协议查询。"""
        out = {}
        for label, uuid in INFO_UUIDS.items():
            try:
                val = bytes(await self.client.read_gatt_char(uuid))
                out[label] = val.decode("utf-8", "replace").strip("\x00 ")
            except Exception as exc:                 # noqa: BLE001
                out[label] = f"<{type(exc).__name__}>"
        try:
            r = await self.query(W.CMD_DEVICE_NAME)
            if r:
                out["名称(协议)"] = r[1].decode("ascii", "replace").strip("\x00")
            r = await self.query(W.CMD_PRINTER_DPI)
            if r and r[1]:
                out["DPI(协议)"] = r[1][0]
            r = await self.query(W.CMD_PRINTER_WIDTH)
            if r and len(r[1]) >= 2:
                out["打印宽度(点)"] = (r[1][0] << 8) | r[1][1]
            r = await self.query(W.CMD_MANUFACTURER)
            if r:
                try:
                    out["厂商(协议)"] = r[1].replace(b"\x00", b"").decode("gbk", "replace")
                except Exception:                    # noqa: BLE001
                    out["厂商(协议)"] = r[1].hex(" ")
        except Exception as exc:                     # noqa: BLE001
            out["协议查询"] = f"<{type(exc).__name__}>"
        return out

    async def print_1bpp(self, raw: bytes, width_dots: int, height_dots: int,
                         *, feed_dots: int = 24) -> bool:
        stream = W.job_from_1bpp(raw, width_dots, height_dots, line_dots=feed_dots)
        if self.echo:
            print(f"    发送 {len(stream)} 字节（{width_dots}x{height_dots} 光栅）", flush=True)
        return await self.send(stream)

    async def locate_next_label(self, wait: float = 1.6) -> None:
        """0C：走到下一张标签的起始边界（机械动作，要等它走完）。"""
        await self.send(W.LOCATE_NEXT)
        await asyncio.sleep(wait)

    # 可打印 / 无任务 / 页面未收全（固件空闲时的几个容忍值）
    READY_CODES = (0, 10, 11)
    # 忙（等一会就好）
    BUSY_CODES = (1, 2)

    # ---------------- 设置读写 ----------------
    async def _get(self, cmd: int, timeout: float = 3.0) -> bytes | None:
        r = await self.query(cmd, b"", timeout=timeout)
        return r[1] if r else None

    async def settings(self) -> dict:
        """一次读全部设置（浓度/速度/纸张类型/间隙/自动关机/计数/能力）。"""
        out: dict = {}
        d = await self._get(W.CMD_DARKNESS)
        if d:
            out["darkness"] = W.decode_darkness(d)
        sp = await self._get(W.CMD_SPEED)
        if sp:
            out["speed"] = W.decode_speed(sp)
        gt = await self._get(W.CMD_GAP_TYPE)
        if gt:
            out["gap_type"] = gt[0]
            out["gap_type_text"] = W.GAP_TYPES.get(gt[0], f"未知({gt[0]})")
        gl = await self._get(W.CMD_GAP_LEN)
        if gl:
            out["gap_len"] = W.decode_gap_len(gl)
        ap = await self._get(W.CMD_AUTOPOWEROFF)
        if ap:
            out["auto_poweroff_min"] = ap[0]
        cnt = await self._get(W.CMD_PRINT_COUNTER)
        if cnt:
            out["counters"] = W.decode_counters(cnt)
        cap = await self._get(W.CMD_CAP_GAPTYPE)
        if cap:
            out["supported_gap_types"] = list(cap)
        sw = await self._get(W.CMD_SOFTWARE_VERSION)
        if sw:
            out["software_version"] = W.decode_version(sw)
        return out

    async def set_darkness(self, level: int) -> bool:
        """浓度（官方 SDK 语义：等级 1..15，发送时 -1）。"""
        if not 1 <= level <= 15:
            raise ValueError("浓度范围 1..15")
        return await self.send_cmd(W.CMD_DARKNESS, bytes([level - 1]))

    async def set_speed(self, level: int) -> bool:
        """速度（等级 1..5，发送时 -1）。"""
        if not 1 <= level <= 5:
            raise ValueError("速度范围 1..5")
        return await self.send_cmd(W.CMD_SPEED, bytes([level - 1]))

    async def set_gap_type(self, gap) -> bool:
        """纸张类型：none/hole/gap/black/transparent 或数字。"""
        val = W.GAP_TYPES[gap] if isinstance(gap, str) else int(gap)
        return await self.send_cmd(W.CMD_GAP_TYPE, bytes([val & 0xFF]))

    async def set_gap_len(self, mm: float) -> bool:
        """间隙长度（单位 mm，内部按 0.01mm 存）。"""
        return await self.send_cmd(W.CMD_GAP_LEN, W.ebv(int(round(mm * 100))))

    async def set_auto_poweroff(self, minutes: int) -> bool:
        return await self.send_cmd(W.CMD_AUTOPOWEROFF, bytes([minutes & 0xFF]))

    async def ensure_ready(self, *, wait: float = 12.0, interval: float = 0.4) -> dict:
        """打印前检查；正在打印/转马达时轮询等到就绪。

        缺纸/无标签/开盖 这类**不会自愈**的状态直接返回不可打印。
        """
        deadline = time.time() + wait
        last = {"ok": False, "error": "未知"}
        while True:
            st = await self.status()
            if st.get("ok"):
                code = st.get("code")
                if code in self.READY_CODES:
                    return {"ready": True, **st}
                if code not in self.BUSY_CODES:
                    return {"ready": False, **st}
                last = st
            else:
                last = st
            if time.time() >= deadline:
                return {"ready": False, **last}
            await asyncio.sleep(interval)

    async def calibrate(self, wait: float = 1.8) -> None:
        """校准：把纸走到下一张标签的**起始**边界。

        注意 0C 的语义是"向前走到下一张的边界"，所以这一步会把当前那张整张吐掉。
        只在**一批打印开始前**做一次，或重新装纸后做一次。
        """
        if self.echo:
            print("    校准：0C 走到下一张标签起点…", flush=True)
        await self.send(W.LOCATE_NEXT)
        await asyncio.sleep(wait)

    async def print_label_1bpp(self, raw: bytes, width_dots: int, height_dots: int,
                               *, width_mm: int | None = None,
                               align_first: bool = False) -> bool:
        """打一张标签。

        实测要点：
        * 每张**结束**都发 0C —— 走纸到下一张起点，下一张自然对齐
        * **开头不要发 0C**：那等于把当前这张整张吐掉，再打印就落到下一张上
        * 只有一批的第一张需要先 calibrate() 一次
        """
        chk = await self.ensure_ready()
        if chk.get("ready") is False:
            if self.echo:
                print(f"    ⚠ 打印前检查未通过：{chk.get('text')}（{chk.get('code')}），已跳过", flush=True)
            return False

        if align_first:
            await self.calibrate()
        stream = W.label_stream(raw, width_dots, height_dots, width_mm=width_mm)
        if self.echo:
            print(f"    标签流 {len(stream)} 字节（{width_dots}x{height_dots} 点）", flush=True)
        return await self.send(stream)

    async def print_batch(self, raw: bytes, width_dots: int, height_dots: int,
                          count: int, *, width_mm: int | None = None) -> int:
        """连续打 count 张：先校准一次，之后每张靠结尾的 0C 自动对齐。"""
        await self.calibrate()
        ok = 0
        for i in range(count):
            if self.echo:
                print(f"    第 {i + 1}/{count} 张", flush=True)
            if await self.print_label_1bpp(raw, width_dots, height_dots, width_mm=width_mm):
                ok += 1
        return ok

    async def print_text(self, text: str, **kw) -> bool:
        """打印文本（自动换行，标签尺寸默认 40x30mm）。"""
        raw, w, h = render_text(text, **kw)
        width_mm = kw.get("width_mm", 40)
        return await self.print_label_1bpp(raw, w, h, width_mm=int(width_mm))

    async def print_qr(self, data: str, **kw) -> bool:
        """打印二维码。"""
        raw, w, h = render_qr(data, **kw)
        width_mm = kw.get("width_mm", 40)
        return await self.print_label_1bpp(raw, w, h, width_mm=int(width_mm))

    async def print_png(self, path: str, *, width_dots: int = 384,
                        threshold: int = 128, feed_dots: int = 24) -> bool:
        from PIL import Image

        img = Image.open(path).convert("L")
        ratio = width_dots / img.width
        img = img.resize((width_dots, max(1, int(img.height * ratio))))
        px = img.load()
        row = (width_dots + 7) // 8
        raw = bytearray(row * img.height)
        for y in range(img.height):
            for x in range(width_dots):
                if px[x, y] < threshold:
                    raw[y * row + (x >> 3)] |= 0x80 >> (x & 7)
        return await self.print_1bpp(bytes(raw), width_dots, img.height, feed_dots=feed_dots)




# --------------------------------------------------------------------------- #
# 渲染：文本 / 二维码 → 1bpp 位图（1=黑）
# --------------------------------------------------------------------------- #
DPI = 203
MM = DPI / 25.4          # 每毫米点数 ≈ 8


def _mm(v: float) -> int:
    return int(round(v * MM))


def blank_canvas(width_mm: float = 40, height_mm: float = 30) -> tuple[bytearray, int, int]:
    w, h = _mm(width_mm), _mm(height_mm)
    return bytearray(((w + 7) // 8) * h), w, h


def _paste(img, canvas: bytearray, cw: int, ch: int, ox: int, oy: int,
           threshold: int = 128) -> None:
    """把 PIL 灰度图贴到 1bpp 画布。"""
    px = img.load()
    row = (cw + 7) // 8
    for y in range(min(img.height, ch - oy)):
        for x in range(min(img.width, cw - ox)):
            if px[x, y] < threshold:
                gy, gx = oy + y, ox + x
                canvas[gy * row + (gx >> 3)] |= 0x80 >> (gx & 7)


def render_text(text: str, *, width_mm: float = 40, height_mm: float = 30,
                font_mm: float = 3.5, margin_mm: float = 1.5,
                line_space: float = 1.2, align: str = "left",
                font_path: str | None = None) -> tuple[bytes, int, int]:
    """把文本渲染成 1bpp 位图（自动按宽度换行）。"""
    from PIL import Image, ImageDraw, ImageFont

    canvas, cw, ch = blank_canvas(width_mm, height_mm)
    size = max(8, _mm(font_mm))
    if font_path is None:
        for cand in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
            if os.path.exists(cand):
                font_path = cand
                break
    font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

    avail = cw - 2 * _mm(margin_mm)
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for chx in para:
            if font.getlength(cur + chx) <= avail:
                cur += chx
            else:
                lines.append(cur)
                cur = chx
        lines.append(cur)

    img_h = int(len(lines) * size * line_space) + 4
    img = Image.new("L", (cw, max(img_h, ch)), 255)
    draw = ImageDraw.Draw(img)
    y = _mm(margin_mm)
    for ln in lines:
        w = font.getlength(ln)
        x = _mm(margin_mm)
        if align == "center":
            x = max(0, int((cw - w) / 2))
        elif align == "right":
            x = max(0, int(cw - w - _mm(margin_mm)))
        draw.text((x, y), ln, font=font, fill=0)
        y += int(size * line_space)
    _paste(img, canvas, cw, ch, 0, 0)
    return bytes(canvas), cw, ch


def render_qr(data: str, *, width_mm: float = 40, height_mm: float = 30,
              box_mm: float = 24, margin_mm: float = 2,
              caption: str = "") -> tuple[bytes, int, int]:
    """把字符串渲染成二维码（居中，可带下方说明文字）。"""
    import qrcode
    from PIL import Image

    qr = qrcode.QRCode(border=1, box_size=1)
    qr.add_data(data)
    qr.make(fit=True)
    qimg = qr.make_image(fill_color="black", back_color="white").convert("L")

    canvas, cw, ch = blank_canvas(width_mm, height_mm)
    size = _mm(box_mm)
    qimg = qimg.resize((size, size), Image.NEAREST)
    ox = (cw - size) // 2
    oy = max(0, _mm(margin_mm))
    _paste(qimg, canvas, cw, ch, ox, oy)

    if caption:
        cimg, ccw, cch = render_text(caption, width_mm=width_mm, height_mm=2,
                                     font_mm=2.8, margin_mm=margin_mm, align="center")
        row = (ccw + 7) // 8
        cy = oy + size + _mm(1)
        for y in range(min(cch, ch - cy)):
            for x in range(ccw):
                if cimg[y * row + (x >> 3)] & (0x80 >> (x & 7)):
                    canvas[(cy + y) * ((cw + 7) // 8) + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(canvas), cw, ch


# --------------------------------------------------------------------------- #
def _demo_image(width: int = 384, height: int = 40) -> tuple[bytes, int, int]:
    row = (width + 7) // 8
    raw = bytearray(row * height)
    for y in range(height):
        for x in range(width):
            if (x // 16 + y // 8) % 2 == 0:
                raw[y * row + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(raw), width, height


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dothantech P1 BLE 客户端")
    ap.add_argument("what", nargs="?", default="demo",
                    choices=["info", "status", "settings", "demo", "print-png",
                             "print-label", "print-text", "print-qr", "cmd"])
    ap.add_argument("arg", nargs="?", help="print-png 的路径 / cmd 的命令码")
    ap.add_argument("--addr", default="28:D4:1E:9A:99:DB")
    ap.add_argument("--feed", type=int, default=24, help="打完走纸多少点")
    ap.add_argument("--width", type=int, default=384, help="打印宽度（点）")
    ap.add_argument("--threshold", type=int, default=128)
    ap.add_argument("--count", type=int, default=1, help="连续打几张（先校准一次）")
    ap.add_argument("--label-h", type=int, default=240,
                    help="标签高度点数（40x30mm 标签 = 240）")
    ap.add_argument("--gap", default="",
                    help="标签间隙类型：none/hole/gap/black/transparent；不设则不动")
    args = ap.parse_args(argv)

    if not args.addr:
        print("需要 --addr 或先扫描")
        return 2

    async with P1Client(args.addr) as p1:
        if args.gap:
            ok = await p1.set_gap_type(args.gap)
            print(f"  设置间隙类型 {args.gap} → {'成功' if ok else '失败'}")
            await asyncio.sleep(0.5)
        if args.what == "info":
            info = await p1.read_info()
            for k, v in info.items():
                print(f"  {k}: {v}")
            return 0

        if args.what == "status":
            st = await p1.status()
            print(f"  状态: {st.get('text')}  (code={st.get('code')})")
            bat = await p1.battery()
            if bat.get("ok"):
                print(f"  电量: {bat['battery_v']}V  格数={bat.get('battery_level')}"
                      f"{'  充电中' if bat.get('charging') else ''}")
            else:
                print(f"  电量: 读不到（{bat.get('error')}）")
            t = await p1.head_temp()
            if t.get("ok"):
                print(f"  打印头: {t['head_temp_c']}°C")
            return 0

        if args.what == "settings":
            st = await p1.settings()
            import json as _json
            print(_json.dumps(st, ensure_ascii=False, indent=2))
            return 0

        if args.what == "print-text":
            ok = await p1.print_text(args.arg or "Hello P1", width_mm=args.gap and 40 or 40,
                                     height_mm=30)
            print(f"  结果: {'已发送 ' + str(p1.sent_bytes) + ' 字节' if ok else '中断'}")
            await asyncio.sleep(1.5)
            return 0 if ok else 1

        if args.what == "print-qr":
            ok = await p1.print_qr(args.arg or "https://example.com", caption=args.arg or "")
            print(f"  结果: {'已发送 ' + str(p1.sent_bytes) + ' 字节' if ok else '中断'}")
            await asyncio.sleep(1.5)
            return 0 if ok else 1

        if args.what == "cmd":
            code = int(args.arg, 0) if args.arg else 0x79
            ok = await p1.send_cmd(code)
            print(f"  命令 0x{code:02X} 发送{'成功' if ok else '失败'}")
            await asyncio.sleep(1.0)
            return 0

        if args.what == "print-label":
            if not args.arg:
                print("print-label 需要图片路径")
                return 2
            from PIL import Image

            img = Image.open(args.arg).convert("L")
            # 按 40mm 宽等比缩放，白底居中
            wdots = args.width
            ratio = min(wdots / img.width, args.label_h / img.height)
            img = img.resize((max(1, int(img.width * ratio)),
                              max(1, int(img.height * ratio))))
            row_bytes = (wdots + 7) // 8
            canvas = bytearray(row_bytes * args.label_h)
            ox = (wdots - img.width) // 2
            oy = (args.label_h - img.height) // 2
            px = img.load()
            for y in range(img.height):
                for x in range(img.width):
                    if px[x, y] < args.threshold:
                        gx, gy = ox + x, oy + y
                        if 0 <= gx < wdots and 0 <= gy < args.label_h:
                            canvas[gy * row_bytes + (gx >> 3)] |= 0x80 >> (gx & 7)
            if args.count > 1:
                n = await p1.print_batch(bytes(canvas), wdots, args.label_h, args.count,
                                         width_mm=wdots // 8)
                print(f"  结果: {n}/{args.count} 张，共 {p1.sent_bytes} 字节")
                await asyncio.sleep(2.0)
                return 0 if n == args.count else 1
            ok = await p1.print_label_1bpp(bytes(canvas), wdots, args.label_h,
                                           width_mm=wdots // 8, align_first=True)
            print(f"  结果: {'已发送 ' + str(p1.sent_bytes) + ' 字节' if ok else '中断'}")
            await asyncio.sleep(1.5)
            return 0 if ok else 1

        if args.what == "print-png":
            if not args.arg:
                print("print-png 需要图片路径")
                return 2
            ok = await p1.print_png(args.arg, width_dots=args.width,
                                    threshold=args.threshold, feed_dots=args.feed)
        else:
            raw, w, h = _demo_image(args.width, 40)
            ok = await p1.print_1bpp(raw, w, h, feed_dots=args.feed)

        print(f"  结果: {'已发送 ' + str(p1.sent_bytes) + ' 字节' if ok else '发送中断'}")
        await asyncio.sleep(1.5)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
