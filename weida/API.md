# WeiDa-Label / Dothantech 标签机 —— 协议 API 文档

> 目标：**不用厂商 App / SDK**，用任意语言通过 **BLE / SPP / USB** 控制标签机。
> 来源：`WeiDa-Label.apk 6.1.20261108` 静态逆向 **+ P1 真机实测（2026-11-20）**
> 参考实现：[`p1_client.py`](p1_client.py)（可直接打印）、[`weida_protocol.py`](weida_protocol.py)（帧层）

标记约定：✅ = 真机验证 / 代码确认；⚠️ = 推断待验；❓ = 未解

---

## 0. P1 实测结论（先看这个，能直接打印）

**设备**：`P1-61085930` / `28:D4:1E:9A:99:DB`
**型号**：`PDBT33F-DF4`（厂商 `PingDong`）　**固件**：`5.20`　**硬件**：`3.1.20240426`

### 0.1 三步就能打印 ✅

```python
# 1) BLE 连接，写 FF02，订阅 FF03 收"信用额度"
# 2) 每收到 FF03 的 [01 nn] 就获得 nn 个额度，每写一片(≤20B)消耗 1 个
# 3) 直接写裸 ESC/POS，不需要任何 AA/BB 帧：
raster = bytes([0x1D, 0x76, 0x30, 0x00])          # GS v 0 m
raster += bytes([xL, xH, yL, yH])                  # 每行字节数、行数
raster += bmp_1bpp                                 # 1=黑
raster += bytes([0x1B, 0x4A, 24])                  # ESC J 24 —— 走纸
await write_ff02_in_chunks(raster, chunk=20)       # 按额度分片
```

实测：一张 **384×40** 的黑白格子图完整打出（用户确认）。
`python weida/p1_client.py demo` 就是这条路径。

### 0.2 信用额度协议 ✅

| 方向 | 通道 | 内容 | 含义 |
|---|---|---|---|
| 设备→主机 | FF03 | `01 07`（连上就有） | 授予 7 个额度 |
| 设备→主机 | FF03 | `02 02 02` | 设备信息/就绪提示（含义未定） |
| 设备→主机 | FF03 | `01 01`（每收一片） | 补 1 个额度 |
| 主机→设备 | FF02 | ≤20 字节/片 | 消耗 1 个额度 |

**额度用完必须等**，否则丢数据。发送节奏：每片后 `sleep(4ms)` 很稳。

### 0.3 还没解出来的

| 项 | 现状 |
|---|---|
| 查询状态（缺纸/电量/温度） | FF01 / FF03 / FF11 / FF12 发 `0x79 0x70 0x44 0x9F 0x40/41 0x77` 全部**无回包**，只有额度 |
| AA/BB 控制帧在 P1 上的作用 | 能发出去，但 P1 不回；打印也用不到它 |
| 任务前导/收尾 | 不需要：直接发 ESC/POS 就出纸 |

> 结论：**打印可控**（够用），**状态读取暂缺**。要补状态，下一步建议抓一次官方 App 的 HCI 日志对照。

---

## 1. 传输层

### 1.1 BLE（推荐）

| 角色 | UUID |
|---|---|
| 服务 | `0000FF00-0000-1000-8000-00805F9B34FB` |
| **写**（主机→打印机） | `0000FF02-…`（properties 0x04 write-no-response / 0x08 write） |
| **通知**（打印机→主机） | `0000FF01-…`（properties 0x10 notify；排除 0x20 indicate） |
| 可选第二通知 | `0000FF03-…`（部分固件启用） |
| CCCD | `00002902-…` |

兼容兜底（代码里的 fallback，按顺序尝试）：

1. `FFE0` 服务 + `FFE1` 特征值（HM-10 类透传模块）
2. 服务 `E7810A71-73AE-499D-8C15-FAA9AEF0C3F2`（别家贴牌打印机）
3. 否则：任取第一个"可写"特征值做写、第一个"可通知"的做读

**BLE 写参数（照抄厂商做法，✅）**

* 写类型：**write without response**（`setWriteType(1)`）
* 分片：`min(剩余, MTU-3)`；**某些机型强制 ≤20 字节**
* 有**信用（credit）流控**：未收到回包前连续写的片数受限
  —— 发太快会丢数据（我们在别的机型上踩过，见 §6）

### 1.2 经典蓝牙 SPP

```
UUID = 00001101-0000-1000-8000-00805F9B34FB
```

用 `createRfcommSocketToServiceRecord` 连接后，直接收发 §2 的字节流（无分片问题）。

### 1.3 USB Host

manifest 声明 `android.hardware.usb.host`，驱动里有 `UsbManager/UsbDevice` 分支（⚠️ 具体接口未解）。

---

## 2. 帧格式（✅ 逐行核对 `com.dothantech.data.b`）

### 2.1 主 → 打印机

```
0xAA | CMD | LEN | PAYLOAD… | CRC
```

* **没有结束字节**，最后一个字节就是 CRC
* `CMD == 0` → **裸数据**：不加任何帧头/长度/校验，payload 原样发出（ESC/POS 就走这条）
* 老固件帧头是 `0x1F`（`k()` 切换），新模式是 `0xAA`（`l()` 切换）

### 2.2 打印机 → 主机

```
0xBB | CMD | LEN | PAYLOAD… | CRC
```

老固件同样是 `0x1F`。

### 2.3 LEN 编码（变长）

| 条件 | 编码 |
|---|---|
| `len < 192` | 1 字节 = `len` |
| `192 ≤ len ≤ 0x3FFF` | 2 字节：`(0xC0 \| (len>>8)), (len & 0xFF)` |

### 2.4 CRC

```python
crc = (~(cmd + sum(payload))) & 0xFF
# 校验：cmd + sum(payload) + crc == 0xFF (mod 256)
#      等价于把 cmd..crc 整段求和再取反 == 0
```

**例外**：全局开关打开时，CRC 位固定填 **`0x88`**，表示"不校验"（解析侧见到就放行）。

### 2.5 最小例子

| 目的 | 字节 |
|---|---|
| 空命令 0x79（能力探测） | `AA 79 00 86` |
| 0x40 + 4 字节载荷 | `AA 40 04 41 01 02 FF 7C` |
| 不校验版本 | `AA 79 00 88` |

---

## 3. 命令通道 API（对应 `com.dothantech.data.d`）

厂商 SDK 内部就这几个方法，自己实现照着写即可：

| 方法 | 含义 | 帧 |
|---|---|---|
| `d(cmd)` | 单字节命令 | `AA cmd 00 crc` |
| `e(cmd, a)` | 1 字节参数 | `AA cmd 01 a crc` |
| `f(cmd, a, b)` | 2 字节参数 | `AA cmd 02 a b crc` |
| `g(cmd, int32)` | 4 字节参数（大端） | `AA cmd 04 … crc` |
| `h(cmd, short, varint)` | 短整数（可 <192 压成 1 字节） | `AA cmd 01/02 … crc` |
| `i(cmd, payload)` | 任意载荷 | `AA cmd LEN payload crc` |
| `k(packet)` | 把上面构造的帧追加进发送缓冲 | — |

---

## 4. 已知命令码（✅ 从驱动里提取）

### 4.1 连接后的能力探测序列

厂商在初始化时逐条发这些单字节命令（不回包就认为不支持该特性）：

```
0x7C 0x79 0x7A 0x75 0x7D 0x71 0x72 0x52 0x57 0x59
0x79 0x44 0x9F 0x83 0x0A 0x29
0x70 0x84 0x43 0x44 0x42 0x88
0x45 0x47 0x48 0x49 0x4D 0x73 0x7F
0x77 + [0x00, 0x00]
```

### 4.2 复合命令

| 命令 | 载荷 | 含义 |
|---|---|---|
| `0x40` | `41 01 02 FF` 或 `41 01 02 FB` | 版本相关（固件 ≥20250825 用 `FF`，否则 `FB`）✅ |

### 4.3 打印相关

| 命令 / 字节 | 含义 |
|---|---|
| `E5 4A n`（`ESC J n`） | 走纸 n 点（>255 自动拆）✅ |
| `1D 76 30 00 xL xH yL yH <data>`（`GS v 0`） | **标准 ESC/POS 光栅位图**（303 机型用这条）✅ |
| `2B <行数-1> <每行字节数> <data>`（cmd = `0x2B`） | 老机型光栅（参数是变长整数）⚠️ |

---

## 5. 打印一张图（最小流程）

```python
from weida_protocol import frame, gs_raster, esc_feed, frame_raw

# 1) 1bpp 位图（1=黑），宽度按机型（常见 384 点 = 48mm @203dpi）
raw = b"\xff" * (48 * 20)          # 384 点宽 × 20 行
# 2) 光栅命令 → 裸数据包（cmd=0 透传）
data = gs_raster(raw, 384, 20)
# 3) 若需要，追加走纸
data += esc_feed(32)
payload = frame_raw(data)          # cmd=0 → 原样发送

# 4) 通过 BLE 写到 FF02（write without response），必要时按 MTU 分片
```

完整可跑示例：`python weida_protocol.py demo`

---

## 6. 流控与节奏（⚠️ 但经验明确）

厂商实现里有信用计数，且**写完一片才允许下一片**。实践建议：

1. 分片 20 字节起步，稳定后再按 MTU 放大
2. 每片之间等 `write-complete`（BLE 栈回调）或 2~5ms
3. 长任务（>1KB）建议等设备回包/状态帧再继续，否则容易丢数据
4. 结束务必发"提交/结束"帧，否则可能不出纸（我们在别的机型上踩过）

---

## 7. 状态 / 回包

打印机 → 主机的帧以 `0xBB` 开头、CMD 与请求对应，载荷里是若干"变长整数 + 参数"。

| 依据 | 说明 |
|---|---|
| `data.PrinterManuInfo` | 解析 `0x40` 系列回包（型号、固件版本、DPI、纸宽）✅ |
| `data.a` 默认机型 | `DPXX-XXXXXXXX` / 203dpi / **384 点宽** / 固件 `2.0.20160118` ✅ |
| `IDzPrinter.PrinterState` | `Connected / Printing / PaperOut / CoverOpen / Overheated / LowVoltage …` ⚠️ 枚举名在 SDK 里，具体码值需抓包确认 |

---

## 8. 还没解出来的（需要一次真机抓包）

| 项 | 为什么需要 |
|---|---|
| 一整个打印任务的**完整前导/收尾帧** | `BitmapPackage` 只负责位图部分，任务前后还有清零/定位/提交 |
| 状态查询命令与回包码值 | 能力探测只区分"支持/不支持"，具体状态位要抓包 |
| 条码 / 文字 / 二维码的原生命令 | 这类标签机通常靠**位图**打印，原生文本命令可能没有 |
| 老机型 `0x2B` 光栅的确切参数语义 | 只有变长编码，缺一次对照 |

**抓包方法（任一）**

1. 手机开发者选项 → 启用"蓝牙 HCI 信息收集日志"，打印一张标签后导出 `btsnoop_hci.log`
2. Android 上装 HCI snoop 工具，或 PC 用 Ubertooth/nRF Sniffer 抓 BLE
3. 抓到后按 §2 解帧（`parse_frames()` 已实现），把命令序列填进本文档

---

## 9. 参考实现

```bash
python weida_protocol.py demo                          # 生成一张测试图的完整字节流
python weida_protocol.py frame 0x79                    # → aa 79 00 86
python weida_protocol.py frame 0x40 410102ff           # → aa 40 04 41 01 02 ff 7c
python weida_protocol.py esc feed 300                  # → 1b 4a ff 1b 4a 2d
```

导出的函数：

| 函数 | 用途 |
|---|---|
| `frame(cmd, payload, no_crc=False)` | 组一帧 |
| `frame_raw(data)` | 裸数据包（ESC/POS 透传） |
| `encode_len(n)` / `encode_short(n)` | 变长整数 |
| `checksum(cmd, payload)` | CRC |
| `gs_raster(row_bytes, w, h)` | ESC/POS 光栅 |
| `esc_feed(dots)` | 走纸 |
| `parse_frames(buf)` | 解打印机回包 |
| `job_from_1bpp(raw, w, h)` | 1bpp → 打印字节流 |
