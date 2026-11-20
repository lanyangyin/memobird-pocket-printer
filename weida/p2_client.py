"""德佟 P2（50x30mm 标签）打印客户端。

P2 的 BLE 是 ISSC 透传（49535343-…），协议仍是 0x1F 帧，但**打印流格式与 P1 不同**：
    PAGE_START(0x20) → PAGE_WIDTH(0x27, 字节) → RLE 行命令(0x2C/0x2D/0x29/0x2E)
    → ESC J n → 0x0C 定位

这些 RLE 命令我们自己还没逆出编码规则，所以**直接用德佟官方 JS SDK 当编码器**
（无头 Chrome 里跑 SDK，取 RawData），拿到字节流再经 BLE 发给打印机。

用法：
    python p2_client.py status
    python p2_client.py print-image a.png
    python p2_client.py print-text "你好"
    python p2_client.py print-qr "https://example.com"
    python p2_client.py darkness 14
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
import p2_sdk  # noqa: E402
from p1_client import P1Client  # noqa: E402

ADDR = "B8:50:44:08:DF:82"
WIDTH_MM, HEIGHT_MM = 50, 30


class P2Client(P1Client):
    def __init__(self, addr: str = ADDR, *, echo: bool = True):
        super().__init__(addr, echo=echo)
        self.label_w = WIDTH_MM
        self.label_h = HEIGHT_MM

    async def prepare(self, darkness: int = 14) -> None:
        """P2 的默认浓度太淡（5），打标签一般要调高。"""
        r = await self.query(W.CMD_DARKNESS, timeout=2.0)
        if r and r[1] and r[1][0] < darkness - 1:
            await self.send_cmd(W.CMD_DARKNESS, bytes([darkness - 1]))
            await asyncio.sleep(0.25)

    async def print_image(self, path: str) -> bool:
        t0 = time.time()
        stream = p2_sdk.encode_png(path, self.label_w, self.label_h)
        if self.echo:
            print(f"    编码 {len(stream)} 字节（{time.time()-t0:.1f}s）", flush=True)
        chk = await self.ensure_ready()
        if chk.get("ready") is False:
            if self.echo:
                print(f"    ⚠ 打印前检查未通过：{chk.get('text')}", flush=True)
            return False
        # 注意：**不要**在发流前发 0C —— 那会把当前这张标签整张吐掉。
        # 官方流自己结尾就带 1B 4A 01 0C。
        ok = await self.send(stream)
        await asyncio.sleep(1.5)
        return ok

    async def print_text(self, text: str, **kw) -> bool:
        path = _render_text_png(text, self.label_w, self.label_h, **kw)
        return await self.print_image(path)

    async def print_qr(self, data: str, caption: str = "") -> bool:
        path = _render_qr_png(data, caption, self.label_w, self.label_h)
        return await self.print_image(path)


def _render_text_png(text: str, w_mm: int, h_mm: int, font_mm: float = 4.5,
                     align: str = "left") -> str:
    from PIL import Image, ImageDraw, ImageFont

    w, h = w_mm * 8, h_mm * 8
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", int(font_mm * 8))
    except Exception:                                # noqa: BLE001
        font = ImageFont.load_default()
    y = int(1.5 * 8)
    for para in text.split("\n"):
        line = ""
        for ch in para:
            if d.textlength(line + ch, font=font) < w - 16:
                line += ch
            else:
                d.text(((w - d.textlength(line, font=font)) / 2 if align == "center" else 8, y),
                       line, font=font, fill="black")
                y += int(font_mm * 8 * 1.25)
                line = ch
        d.text(((w - d.textlength(line, font=font)) / 2 if align == "center" else 8, y),
               line, font=font, fill="black")
        y += int(font_mm * 8 * 1.25)
    path = os.path.join(os.environ.get("TEMP", "/tmp"), f"p2_text_{int(time.time()*1000)}.png")
    img.save(path)
    return path


def _render_qr_png(data: str, caption: str, w_mm: int, h_mm: int) -> str:
    import qrcode
    from PIL import Image, ImageDraw, ImageFont

    w, h = w_mm * 8, h_mm * 8
    img = Image.new("RGB", (w, h), "white")
    qr = qrcode.QRCode(border=1, box_size=1)
    qr.add_data(data)
    qr.make(fit=True)
    qimg = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    size = min(w - 16, h - 16 - (40 if caption else 0))
    qimg = qimg.resize((size, size), Image.NEAREST)
    img.paste(qimg, ((w - size) // 2, 8))
    if caption:
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 22)
        except Exception:                            # noqa: BLE001
            font = ImageFont.load_default()
        tw = d.textlength(caption, font=font)
        d.text(((w - tw) / 2, 8 + size + 4), caption, font=font, fill="black")
    path = os.path.join(os.environ.get("TEMP", "/tmp"), f"p2_qr_{int(time.time()*1000)}.png")
    img.save(path)
    return path


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="德佟 P2 标签打印")
    ap.add_argument("what", nargs="?", default="status",
                    choices=["status", "info", "settings", "print-image", "print-text",
                             "print-qr", "darkness", "cmd"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--addr", default=ADDR)
    ap.add_argument("--darkness", type=int, default=14)
    ap.add_argument("--width-mm", type=int, default=WIDTH_MM)
    ap.add_argument("--height-mm", type=int, default=HEIGHT_MM)
    args = ap.parse_args(argv)

    async with P2Client(args.addr, echo=False) as p2:
        p2.label_w, p2.label_h = args.width_mm, args.height_mm

        if args.what == "status":
            st = await p2.status()
            print(f"  状态: {st.get('text')} (code={st.get('code')})")
            r = await p2.query(W.CMD_DARKNESS, timeout=2)
            if r:
                print(f"  浓度: {r[1][0]}")
            return 0

        if args.what == "info":
            for k, v in (await p2.read_info()).items():
                print(f"  {k}: {v}")
            return 0

        if args.what == "settings":
            import json
            print(json.dumps(await p2.settings(), ensure_ascii=False, indent=2))
            return 0

        if args.what == "darkness":
            level = int(args.arg) if args.arg else args.darkness
            await p2.send_cmd(W.CMD_DARKNESS, bytes([level - 1]))
            await asyncio.sleep(0.4)
            r = await p2.query(W.CMD_DARKNESS, timeout=2)
            print(f"  浓度设为 {level} → 读回 {r[1][0] if r else '?'}")
            return 0

        if args.what == "cmd":
            code = int(args.arg, 0) if args.arg else 0x70
            r = await p2.query(code)
            print(f"  0x{code:02X} → {r[1].hex(' ') if r else '无回包'}")
            return 0

        await p2.prepare(args.darkness)

        if args.what == "print-image":
            if not args.arg:
                print("print-image 需要图片路径")
                return 2
            ok = await p2.print_image(args.arg)
        elif args.what == "print-text":
            ok = await p2.print_text(args.arg or "Hello P2")
        else:
            ok = await p2.print_qr(args.arg or "https://example.com", caption=args.arg or "")

        print(f"  结果: {'已发送 ' + str(p2.sent_bytes) + ' 字节' if ok else '失败'}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
