"""让 P1Client 自动识别 BLE 通道：P1(FF00+FF03 信用) / P2(49535343 透传)。"""
import io
import os

P = os.path.join(os.getcwd(), "weida", "p1_client.py")
s = io.open(P, encoding="utf-8").read()

old = '''        await self.client.start_notify(FF03, self._on_ff03)
        try:
            await self.client.start_notify(FF01, self._on_ff01)
        except Exception:                            # noqa: BLE001
            pass
        await asyncio.sleep(1.2)                     # 等固件准备好 + 初始额度'''
new = '''        # ---- 自动识别通道 ----
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
        await asyncio.sleep(1.2)                     # 等固件准备好 + 初始额度'''
assert old in s
s = s.replace(old, new, 1)

# 新增：通道选择 + 通用回调
s = s.replace('''    def _on_ff03(self, _sender, data: bytearray) -> None:
        raw = bytes(data)
        self._log(raw.hex(" "), "FF03")
        if len(raw) >= 2 and raw[0] == 0x01:
            # 信用额度：01 nn
            self._loop.create_task(self._grant(raw[1]))
        for cmd, payload in W.parse_frames(raw):
            self.rxq.append((cmd, payload))
            if self._waiter is not None and not self._waiter.done():
                self._waiter.set_result((cmd, payload))
        # 0x40 主动上报（电量/状态）
        for cmd, payload in W.parse_frames(raw):
            if cmd == W.CMD_PUSH_STATUS:
                self.push_status.append(W.decode_push(payload))

    def _on_ff01(self, _sender, data: bytearray) -> None:
        raw = bytes(data)
        self._log(raw.hex(" "), "FF01")
        for cmd, payload in W.parse_frames(raw):
            self.rxq.append((cmd, payload))
            if self._waiter is not None and not self._waiter.done():
                self._waiter.set_result((cmd, payload))''',
'''    # ---------------- 通道识别 ----------------
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
                self._waiter.set_result((cmd, payload))''')
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('P1Client: 通道自动识别')
