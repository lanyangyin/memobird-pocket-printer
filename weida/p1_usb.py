r"""P1 USB 客户端（Windows USB Printer 接口，无需装驱动/换驱动）。

原理：直接打开 Windows 自带的 usbprint 设备接口
      \\?\USB#VID_xxxx&PID_xxxx&MI_00#...{28d78fad-5a12-11d1-ae5b-0000f803a8c2}
用重叠 I/O 读写，协议与 BLE/串口完全相同（0x1F 帧）。

用法：
    python p1_usb.py ports                 # 列出 usbprint 接口
    python p1_usb.py info
    python p1_usb.py status
    python p1_usb.py print-text "你好"
    python p1_usb.py print-label a.png --count 2
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import weida_protocol as W  # noqa: E402
from p1_client import P1Client, render_text  # noqa: E402

GUID_USBPRINT = "{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_FLAG_OVERLAPPED = 0x40000000
OPEN_EXISTING = 3
ERROR_IO_PENDING = 997

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)

k32.CreateFileW.restype = wt.HANDLE
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                            wt.DWORD, wt.DWORD, wt.HANDLE]
k32.CreateEventW.restype = wt.HANDLE
k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD), ("hEvent", wt.HANDLE)]


k32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_char_p, wt.DWORD,
                          ctypes.POINTER(wt.DWORD), ctypes.POINTER(_OVERLAPPED)]
k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_char_p, wt.DWORD,
                         ctypes.POINTER(wt.DWORD), ctypes.POINTER(_OVERLAPPED)]
k32.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.POINTER(_OVERLAPPED),
                                    ctypes.POINTER(wt.DWORD), wt.BOOL]


def _guid(s: str) -> _GUID:
    u = uuid.UUID(s.strip("{}"))
    g = _GUID()
    g.Data1, g.Data2, g.Data3 = u.fields[0], u.fields[1], u.fields[2]
    for i, b in enumerate(u.bytes[8:]):
        g.Data4[i] = b
    return g


setupapi.SetupDiGetClassDevsW.restype = wt.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(_GUID), wt.LPCWSTR,
                                          wt.HWND, wt.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(_GUID), wt.DWORD, ctypes.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
    ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]


def find_usbprint_paths() -> list[str]:
    """枚举 usbprint 设备接口路径。"""
    paths: list[str] = []
    g = _guid(GUID_USBPRINT)
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not hdev or hdev == ctypes.c_void_p(-1).value:
        return paths
    try:
        for i in range(16):
            did = ctypes.create_string_buffer(64)
            ctypes.cast(did, ctypes.POINTER(wt.DWORD))[0] = 32
            if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(g),
                                                        i, did):
                break
            need = wt.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, did, None, 0,
                                                      ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8
            if setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, did, buf, need.value,
                                                         ctypes.byref(need), None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return paths


def open_usbprint(path: str):
    h = k32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 1 | 2, None,
                        OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
    if not h or h == ctypes.c_void_p(-1).value:
        raise OSError(f"打开 usbprint 失败 err={ctypes.get_last_error()}")
    return h


class P1UsbClient(P1Client):
    """USB 版客户端：同一个 API。"""

    def __init__(self, path: str | None = None, *, echo: bool = True):
        super().__init__(path or "usb", echo=echo)
        self.path = path
        self.h = None
        self.reader = W.FrameReader()
        self._read_task: asyncio.Task | None = None
        self._closing = False

    async def __aenter__(self):
        self._loop = asyncio.get_running_loop()
        path = self.path
        if not path:
            cands = find_usbprint_paths()
            if not cands:
                raise OSError("没有找到 usbprint 接口（打印机 USB 插好了吗？）")
            path = cands[0]
        self.h = open_usbprint(path)
        self.path = path
        await self._drain()                      # 清掉上次残留的回包
        self._read_task = asyncio.create_task(self._read_loop())
        try:
            await self.send_cmd(W.CMD_ENABLE_SETTING, b"\x7f")
            await asyncio.sleep(0.2)
        except Exception:                        # noqa: BLE001
            pass
        return self

    async def __aexit__(self, *exc):
        self._closing = True
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None
        return False

    # ---------------- 底层 IO ----------------
    def _write_sync(self, data: bytes, chunk: int = 1024) -> int:
        total = 0
        for i in range(0, len(data), chunk):
            part = data[i:i + chunk]
            ev = k32.CreateEventW(None, True, False, None)
            ov = _OVERLAPPED()
            ov.hEvent = ev
            n = wt.DWORD(0)
            ok = k32.WriteFile(self.h, part, len(part), ctypes.byref(n),
                               ctypes.byref(ov))
            if not ok:
                if ctypes.get_last_error() != ERROR_IO_PENDING:
                    k32.CloseHandle(ev)
                    raise OSError(f"写失败 err={ctypes.get_last_error()}")
                if k32.WaitForSingleObject(ev, 5000) != 0:
                    k32.CloseHandle(ev)
                    raise OSError("写超时")
                k32.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(n), False)
            k32.CloseHandle(ev)
            total += n.value
        return total

    def _read_sync(self, size: int = 512, timeout_ms: int = 500) -> bytes:
        ev = k32.CreateEventW(None, True, False, None)
        ov = _OVERLAPPED()
        ov.hEvent = ev
        buf = ctypes.create_string_buffer(size)
        n = wt.DWORD(0)
        ok = k32.ReadFile(self.h, buf, size, ctypes.byref(n), ctypes.byref(ov))
        if not ok:
            if ctypes.get_last_error() != ERROR_IO_PENDING:
                k32.CloseHandle(ev)
                return b""
            if k32.WaitForSingleObject(ev, timeout_ms) != 0:
                k32.CancelIo(self.h)
                k32.CloseHandle(ev)
                return b""
            k32.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(n), False)
        k32.CloseHandle(ev)
        return buf.raw[: n.value]

    async def _drain(self) -> None:
        """丢掉残留回包（USB 回包是按顺序排队的）。"""
        loop = asyncio.get_running_loop()
        for _ in range(6):
            data = await loop.run_in_executor(None, self._read_sync, 512, 120)
            if not data:
                break
            self.reader.feed(data)

    async def _read_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._closing:
            try:
                data = await loop.run_in_executor(None, self._read_sync, 512, 300)
            except Exception:                    # noqa: BLE001
                return
            if not data:
                continue
            for cmd, payload in self.reader.feed(data):
                self.rxq.append((cmd, payload))
                if self.echo:
                    print(f"    <- {cmd:02X} {payload.hex(' ')}", flush=True)
                if cmd == W.CMD_PUSH_STATUS:
                    self.push_status.append(W.decode_push(payload))
                if self._waiter is not None and not self._waiter.done():
                    self._waiter.set_result((cmd, payload))

    async def send(self, data: bytes, *, timeout: float = 8.0) -> bool:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._write_sync, data)
        except Exception as exc:                 # noqa: BLE001
            if self.echo:
                print(f"    ⚠ USB 写失败：{type(exc).__name__}: {exc}", flush=True)
            return False
        self.sent_bytes += len(data)
        return True


def list_ports() -> int:
    paths = find_usbprint_paths()
    if not paths:
        print("  没有 usbprint 接口（USB 插好了吗？）")
        return 1
    print("  usbprint 接口：")
    for p in paths:
        tag = ""
        low = p.lower()
        if "vid_3533" in low and "pid_5a11" in low:
            tag = "  ← P1 Label Printer"
        print(f"    {p}{tag}")
    return 0


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P1 USB 客户端")
    ap.add_argument("what", nargs="?", default="status",
                    choices=["ports", "info", "status", "settings", "print-text",
                             "print-label", "cmd"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--path", default=None, help="usbprint 设备路径（默认自动找）")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--label-h", type=int, default=240)
    args = ap.parse_args(argv)

    if args.what == "ports":
        return list_ports()

    async with P1UsbClient(args.path, echo=False) as p1:
        if args.what == "info":
            for k, v in (await p1.read_info()).items():
                print(f"  {k}: {v}")
            return 0
        if args.what == "status":
            st = await p1.status()
            print(f"  状态: {st.get('text')}  (code={st.get('code')})")
            bat = await p1.battery()
            if bat.get("ok"):
                print(f"  电量: {bat['battery_v']}V  格数={bat.get('battery_level')}")
            t = await p1.head_temp()
            if t.get("ok"):
                print(f"  打印头: {t['head_temp_c']}°C")
            return 0
        if args.what == "settings":
            import json
            print(json.dumps(await p1.settings(), ensure_ascii=False, indent=2))
            return 0
        if args.what == "cmd":
            code = int(args.arg, 0) if args.arg else 0x70
            r = await p1.query(code)
            print(f"  0x{code:02X} → {r[1].hex(' ') if r else '无回包'}")
            return 0
        if args.what == "print-text":
            ok = await p1.print_text(args.arg or "USB 打印测试")
            print(f"  结果: {'已发送 ' + str(p1.sent_bytes) + ' 字节' if ok else '中断'}")
            return 0 if ok else 1

        # print-label
        if not args.arg:
            print("print-label 需要图片路径")
            return 2
        from PIL import Image
        img = Image.open(args.arg).convert("L")
        ratio = min(args.width / img.width, args.label_h / img.height)
        img = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))
        row_bytes = (args.width + 7) // 8
        canvas = bytearray(row_bytes * args.label_h)
        ox, oy = (args.width - img.width) // 2, (args.label_h - img.height) // 2
        px = img.load()
        for y in range(img.height):
            for x in range(img.width):
                if px[x, y] < 128:
                    gx, gy = ox + x, oy + y
                    canvas[gy * row_bytes + (gx >> 3)] |= 0x80 >> (gx & 7)
        if args.count > 1:
            n = await p1.print_batch(bytes(canvas), args.width, args.label_h, args.count,
                                     width_mm=args.width // 8)
            print(f"  结果: {n}/{args.count} 张")
            return 0 if n == args.count else 1
        ok = await p1.print_label_1bpp(bytes(canvas), args.width, args.label_h,
                                       width_mm=args.width // 8, align_first=True)
        print(f"  结果: {'已发送 ' + str(p1.sent_bytes) + ' 字节' if ok else '中断'}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
