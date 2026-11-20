"""通过 Windows 打印队列（德佟 P2 驱动）打印标签 —— 最省事的一条路。

驱动负责把位图编码成打印机认识的数据，我们只负责画图。
标签尺寸 50x30mm @203dpi = 400 x 240 点。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys

import win32con
import win32print
import win32ui
import win32gui
from PIL import Image, ImageWin

DEFAULT_PRINTER = "P2 Label Printer"
DPI = 203
MM = DPI / 25.4


def list_papers(printer: str = DEFAULT_PRINTER) -> list[tuple[int, str]]:
    """枚举驱动支持的纸型（DC_PAPERS / DC_PAPERNAMES）。"""
    spool = ctypes.WinDLL("winspool.drv")
    DC_PAPERS, DC_PAPERNAMES = 2, 16
    try:
        h = win32print.OpenPrinter(printer)
        try:
            info = win32print.GetPrinter(h, 2)
            port = info["pPortName"]
        finally:
            win32print.ClosePrinter(h)
    except Exception:                                # noqa: BLE001
        return []

    n = spool.DeviceCapabilitiesW(printer, port, DC_PAPERS, None, None)
    if n <= 0:
        return []
    ids = (ctypes.c_short * n)()
    spool.DeviceCapabilitiesW(printer, port, DC_PAPERS, ids, None)
    buf = ctypes.create_unicode_buffer(64 * n)
    spool.DeviceCapabilitiesW(printer, port, DC_PAPERNAMES, buf, None)
    return [(ids[i], buf[64 * i:].split("\x00")[0]) for i in range(n)]


def print_image(path: str, printer: str = DEFAULT_PRINTER,
                width_mm: float = 50, height_mm: float = 30,
                copies: int = 1, paper_id: int = 200) -> None:
    """把图片按 width_mm x height_mm 印到指定打印机。"""
    img = Image.open(path).convert("RGB")
    w, h = int(width_mm * MM), int(height_mm * MM)
    # 等比缩放并居中到标签画布
    canvas = Image.new("RGB", (w, h), "white")
    ratio = min(w / img.width, h / img.height)
    resized = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))
    canvas.paste(resized, ((w - resized.width) // 2, (h - resized.height) // 2))

    # 用 DEVMODE 指定纸型（id=200 = "E 50 x 30 mm"）
    hprinter = win32print.OpenPrinter(printer)
    try:
        dm = win32print.GetPrinter(hprinter, 2)["pDevMode"]
    finally:
        win32print.ClosePrinter(hprinter)
    if dm and paper_id:
        dm.PaperSize = paper_id
        dm.Fields |= 0x00000002          # DM_PAPERSIZE
        dm.Orientation = win32con.DMORIENT_PORTRAIT
        dm.Fields |= 0x00000001          # DM_ORIENTATION

    hdc_raw = win32gui.CreateDC("WINSPOOL", printer, dm)
    hdc = win32ui.CreateDCFromHandle(hdc_raw)
    try:
        hdc.StartDoc("P2 Label")
        for _ in range(copies):
            hdc.StartPage()
            dib = ImageWin.Dib(canvas)
            dib.draw(hdc.GetHandleOutput(), (0, 0, w, h))
            hdc.EndPage()
        hdc.EndDoc()
    finally:
        hdc.DeleteDC()


def render_text(text: str, path: str, width_mm: float = 50, height_mm: float = 30,
                font_mm: float = 4.5, border: bool = False) -> str:
    from PIL import ImageDraw, ImageFont

    w, h = int(width_mm * MM), int(height_mm * MM)
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", int(font_mm * MM))
    except Exception:                                # noqa: BLE001
        font = ImageFont.load_default()
    y = int(1.5 * MM)
    for para in text.split("\n"):
        line = ""
        for ch in para:
            if d.textlength(line + ch, font=font) < w - 2 * int(1.5 * MM):
                line += ch
            else:
                d.text((int(1.5 * MM), y), line, font=font, fill="black")
                y += int(font_mm * MM * 1.3)
                line = ch
        d.text((int(1.5 * MM), y), line, font=font, fill="black")
        y += int(font_mm * MM * 1.3)
    if border:
        d.rectangle([1, 1, w - 2, h - 2], outline="black", width=2)
    img.save(path)
    return path


def render_qr(data: str, path: str, width_mm: float = 50, height_mm: float = 30,
              caption: str = "") -> str:
    """画二维码（可带下方说明），保存成 PNG。"""
    import qrcode
    from PIL import ImageDraw, ImageFont

    w, h = int(width_mm * MM), int(height_mm * MM)
    img = Image.new("RGB", (w, h), "white")
    qr = qrcode.QRCode(border=1, box_size=1)
    qr.add_data(data)
    qr.make(fit=True)
    qimg = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    cap_h = int(6 * MM) if caption else 0
    size = min(w - int(2 * MM), h - int(2 * MM) - cap_h)
    qimg = qimg.resize((size, size), Image.NEAREST)
    img.paste(qimg, ((w - size) // 2, int(1 * MM)))
    if caption:
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", int(3.2 * MM))
        except Exception:                            # noqa: BLE001
            font = ImageFont.load_default()
        tw = d.textlength(caption, font=font)
        d.text(((w - tw) / 2, int(1 * MM) + size + 2), caption, font=font, fill="black")
    img.save(path)
    return path


def render_label(lines: list[str], path: str, width_mm: float = 50, height_mm: float = 30,
                 big: str | None = None, big_mm: float = 7.0, border: bool = False) -> str:
    """排版一个标签：可选大标题 + 若干行小字。"""
    from PIL import ImageDraw, ImageFont

    w, h = int(width_mm * MM), int(height_mm * MM)
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    y = int(1.2 * MM)
    if big:
        try:
            f = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", int(big_mm * MM))
        except Exception:                            # noqa: BLE001
            f = ImageFont.load_default()
        d.text((int(1.5 * MM), y), big, font=f, fill="black")
        y += int(big_mm * MM * 1.25)
    try:
        fs = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", int(3.4 * MM))
    except Exception:                                # noqa: BLE001
        fs = ImageFont.load_default()
    for line in lines:
        d.text((int(1.5 * MM), y), line, font=fs, fill="black")
        y += int(3.4 * MM * 1.35)
    if border:
        d.rectangle([1, 1, w - 2, h - 2], outline="black", width=2)
    img.save(path)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="通过打印驱动打 P2 标签")
    ap.add_argument("what", nargs="?", default="papers",
                    choices=["papers", "print-image", "print-text", "print-qr",
                             "print-label", "test"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--printer", default=DEFAULT_PRINTER)
    ap.add_argument("--width-mm", type=float, default=50)
    ap.add_argument("--height-mm", type=float, default=30)
    ap.add_argument("--copies", type=int, default=1)
    ap.add_argument("--paper-id", type=int, default=200, help="纸型 id（200 = 50x30mm）")
    args = ap.parse_args(argv)

    if args.what == "papers":
        papers = list_papers(args.printer)
        if not papers:
            print("  没读到纸型列表")
            return 1
        print(f"  {args.printer} 支持 {len(papers)} 种纸型：")
        for pid, name in papers:
            print(f"    id={pid:<4} {name}")
        return 0

    if args.what == "print-text":
        path = os.path.join(os.environ.get("TEMP", "/tmp"), "p2_spooler_text.png")
        render_text(args.arg or "P2 打印队列测试", path,
                    args.width_mm, args.height_mm, border=True)
        print_image(path, args.printer, args.width_mm, args.height_mm, args.copies,
                    args.paper_id)
        print("  已提交打印任务")
        return 0

    if args.what == "print-qr":
        path = os.path.join(os.environ.get("TEMP", "/tmp"), "p2_spooler_qr.png")
        render_qr(args.arg or "https://example.com", path,
                  args.width_mm, args.height_mm, caption=args.arg or "")
        print_image(path, args.printer, args.width_mm, args.height_mm, args.copies,
                    args.paper_id)
        print("  已提交打印任务")
        return 0

    if args.what == "print-label":
        path = os.path.join(os.environ.get("TEMP", "/tmp"), "p2_spooler_label.png")
        parts = (args.arg or "标题|第一行|第二行").split("|")
        render_label(parts[1:], path, args.width_mm, args.height_mm,
                     big=parts[0], border=True)
        print_image(path, args.printer, args.width_mm, args.height_mm, args.copies,
                    args.paper_id)
        print("  已提交打印任务")
        return 0

    if args.what == "test":
        path = os.path.join(os.environ.get("TEMP", "/tmp"), "p2_spooler_test.png")
        render_text("50x30 测试\nWindows 驱动", path, args.width_mm, args.height_mm, border=True)
        print_image(path, args.printer, args.width_mm, args.height_mm, args.copies,
                    args.paper_id)
        print("  已提交打印任务")
        return 0

    if not args.arg:
        print("print-image 需要图片路径")
        return 2
    print_image(args.arg, args.printer, args.width_mm, args.height_mm, args.copies)
    print("  已提交打印任务")
    return 0


if __name__ == "__main__":
    sys.exit(main())
