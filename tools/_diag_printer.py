"""三层诊断：GATT 是否正常 → 写入是否被接受 → 应用层是否应答。

用法： python tools/_diag_printer.py [地址]
"""
import asyncio
import sys

sys.path.insert(0, ".")

ADDR = sys.argv[1] if len(sys.argv) > 1 else "00:15:83:E4:7A:F2"


async def main():
    from bleak import BleakClient

    from memobird_printer import device, packet

    print("=== 1) 连接 + GATT 层 ===")
    client = BleakClient(ADDR, timeout=20)
    await client.connect()
    print("   is_connected:", client.is_connected)

    print("=== 2) 读设备信息服务（只读特征值，验证 GATT 通不通）===")
    for uuid in ("00002a29-0000-1000-8000-00805f9b34fb",   # 厂商名
                 "00002a24-0000-1000-8000-00805f9b34fb",   # 型号
                 "00002a26-0000-1000-8000-00805f9b34fb"):  # 固件版本
        try:
            val = await client.read_gatt_char(uuid)
            print(f"   {uuid[4:8]}: {bytes(val)!r}")
        except Exception as exc:                            # noqa: BLE001
            print(f"   {uuid[4:8]}: 读失败 {type(exc).__name__}: {exc}")

    print("=== 3) 订阅通知 ff01 ===")
    got = []

    def on_notify(_s, data: bytearray):
        got.append(bytes(data))
        print(f"   <- notify {bytes(data).hex(' ')}")

    try:
        await client.start_notify("0000ff01-0000-1000-8000-00805f9b34fb", on_notify)
        print("   订阅成功")
    except Exception as exc:                                # noqa: BLE001
        print("   订阅失败:", type(exc).__name__, exc)

    print("=== 4) 写入 ff02：状态查询（write without response）===")
    frame = device.status_frame()
    try:
        await client.write_gatt_char("0000ff02-0000-1000-8000-00805f9b34fb",
                                     frame, response=False)
        print("   写入成功:", frame.hex(" "))
    except Exception as exc:                                # noqa: BLE001
        print("   写入失败:", type(exc).__name__, exc)

    await asyncio.sleep(2.0)
    print("   收到通知数量:", len(got))

    print("=== 5) 再试一次（write with response）===")
    try:
        await client.write_gatt_char("0000ff02-0000-1000-8000-00805f9b34fb",
                                     frame, response=True)
        print("   写入成功（带应答）")
    except Exception as exc:                                # noqa: BLE001
        print("   写入失败:", type(exc).__name__, exc)
    await asyncio.sleep(2.0)
    print("   收到通知数量:", len(got))

    print("=== 6) 试写设置帧（cmd 0x03 浓度=10）===")
    try:
        await client.write_gatt_char("0000ff02-0000-1000-8000-00805f9b34fb",
                                     device.setting_frame(0x02, 10), response=False)
        print("   已写")
    except Exception as exc:                                # noqa: BLE001
        print("   失败:", type(exc).__name__, exc)
    await asyncio.sleep(2.0)
    print("   收到通知数量:", len(got))

    print("=== 7) 解析收到的帧 ===")
    for f in got:
        info = device.parse_status(f)
        print("   ", f.hex(" ")[:60], "→", "status" if info else "其它")

    await client.disconnect()
    print("=== 结束（断开）===")


asyncio.run(main())
