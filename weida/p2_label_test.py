"""P2 50x30mm 标签标定：打印头只有 48mm，看内容在 50mm 标签上的落位。"""
import asyncio
import sys

sys.path.insert(0, r"C:\Users\18898\PycharmProjects\apk-re-yddyj\weida")
import weida_protocol as W  # noqa: E402
from p1_client import _mm  # noqa: E402


def put_px(buf, width, x, y, on=True):
    if x < 0 or y < 0:
        return
    row = (width + 7) // 8
    idx = y * row + (x >> 3)
    if idx >= len(buf):
        return
    if on:
        buf[idx] |= 0x80 >> (x & 7)
    else:
        buf[idx] &= ~(0x80 >> (x & 7)) & 0xFF


def rect(buf, width, x0, y0, x1, y1, thick=1):
    for t in range(thick):
        for x in range(x0, x1 + 1):
            put_px(buf, width, x, y0 + t)
            put_px(buf, width, x, y1 - t)
        for y in range(y0, y1 + 1):
            put_px(buf, width, x0 + t, y)
            put_px(buf, width, x1 - t, y)


def draw_text(buf, width, x, y, text, size=20):
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("msyh.ttc", size)
    except Exception:
        font = ImageFont.load_default()
    img = Image.new("L", (460, size + 10), 255)
    ImageDraw.Draw(img).text((0, 2), text, font=font, fill=0)
    px = img.load()
    row = (width + 7) // 8
    for yy in range(img.height):
        for xx in range(img.width):
            if px[xx, yy] < 128:
                gx, gy = x + xx, y + yy
                if 0 <= gx < width and gy * row < len(buf):
                    put_px(buf, width, gx, gy)

ADDR = sys.argv[1] if len(sys.argv) > 1 else "B8:50:44:08:DF:82"
WRITE = "49535343-8841-43f4-a8d4-ecbe34729bb3"
NOTIFY = "49535343-1e4d-4bd9-ba61-23c647249616"

HEAD_DOTS = 384          # 打印头 48mm
LABEL_MM = 50
HEIGHT_MM = 30


def build() -> tuple[bytes, int, int]:
    w = HEAD_DOTS
    h = _mm(HEIGHT_MM)                     # 240
    buf = bytearray(((w + 7) // 8) * h)
    rect(buf, w, 0, 0, w - 1, h - 1, thick=2)

    # 每 5mm 刻度（沿着上下边缘）
    for mm in range(5, 48, 5):
        x = _mm(mm)
        for y in range(6, 20):
            put_px(buf, w, x, y)
        for y in range(h - 20, h - 6):
            put_px(buf, w, x, y)
    # 每 5mm 刻度（左侧）
    for mm in range(5, 30, 5):
        y = _mm(mm)
        for x in range(6, 20):
            put_px(buf, w, x, y)

    draw_text(buf, w, _mm(10), _mm(4), "50 x 30 mm", 30)
    draw_text(buf, w, _mm(10), _mm(9), "head 48mm = 384dots", 22)
    draw_text(buf, w, _mm(10), _mm(14), "P2 标定", 22)
    draw_text(buf, w, _mm(10), _mm(20), "边框=可打印范围", 20)
    return bytes(buf), w, h


async def main():
    from bleak import BleakClient

    raw, w, h = build()
    print(f"  画布 {w}x{h} 点（{w/8:.0f}x{h/8:.0f}mm）")

    c = BleakClient(ADDR, timeout=25)
    await c.connect()
    reader = W.FrameReader()
    got = []

    def on(_s, d):
        for cmd, payload in reader.feed(bytes(d)):
            got.append((cmd, payload))

    await c.start_notify(NOTIFY, on)
    await asyncio.sleep(0.8)

    async def send(data: bytes, chunk: int = 180):
        for i in range(0, len(data), chunk):
            await c.write_gatt_char(WRITE, data[i:i + chunk], response=False)
            await asyncio.sleep(0.005)

    # 先设纸张类型 = 间隙纸
    await send(W.frame(W.CMD_GAP_TYPE, bytes([2])))
    await asyncio.sleep(0.5)
    got.clear()
    await send(W.frame(W.CMD_GAP_TYPE))
    await asyncio.sleep(0.6)
    print(f"  纸张类型: {[p.hex(' ') for _, p in got] or '无回包'}")

    # 校准
    print("  0C 校准…")
    await send(W.LOCATE_NEXT)
    await asyncio.sleep(2.0)

    stream = W.label_stream(raw, w, h, width_mm=48)
    print(f"  标签流 {len(stream)} 字节")
    await send(stream)
    await asyncio.sleep(2.0)

    # 打完查状态
    got.clear()
    await send(W.frame(W.CMD_IS_PRINTABLE))
    await asyncio.sleep(0.8)
    for cmd, payload in got:
        if cmd == 0x70:
            print(f"  状态: {W.decode_status(payload)['text']}")

    await c.disconnect()
    return 0


sys.exit(asyncio.run(main()))
