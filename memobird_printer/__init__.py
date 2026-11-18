"""memobird_printer — 咕咕机 / 有道口袋打印机 通用 Python 控制库

三条后端（按推荐顺序）：

    lan    局域网 HTTP  http://<ip>/sys/printer   无线机型，无需账号
    ble    蓝牙 GATT（bleak）                     有道口袋打印机 / GT1 / G4
    spp    经典蓝牙 SPP（pyserial + COM 口）       Android 侧走经典蓝牙的机型
    cloud  咕咕机开放平台 open.memobird.cn        需要 ak（兜底）

典型用法：

    from memobird_printer import LanPrinter, BlePrinter, prepare, dither_to_raw

    # 局域网
    p = LanPrinter("192.168.1.50")
    p.print_text("hello 咕咕机")
    p.print_raw_image(*dither_to_raw(prepare("图片.png")))

    # 蓝牙
    import asyncio
    async def main():
        async with BlePrinter("AA:BB:CC:DD:EE:FF") as b:
            await b.print_text("蓝牙打印")
    asyncio.run(main())
"""
from __future__ import annotations

from .image import (
    PRINTER_WIDTH,
    dither_to_raw,
    image_to_bmp,
    prepare,
    preview,
    raw_to_bmp,
    render_text,
)
from .lan import LanPrinter, discover
from .cloud import CloudPrinter
from .ble import BlePrinter, SppPrinter, scan, gatt_dump
from . import packet

__all__ = [
    "PRINTER_WIDTH",
    "LanPrinter", "discover",
    "BlePrinter", "SppPrinter", "scan", "gatt_dump",
    "CloudPrinter",
    "packet",
    "prepare", "render_text", "dither_to_raw", "raw_to_bmp", "image_to_bmp", "preview",
]

__version__ = "1.3.1"
