# WeiDa-Label / Dothantech 标签机 —— 协议 API 文档

> **不用厂商 App / SDK**，用任意语言通过 BLE 控制标签机。
> 来源：`WeiDa-Label.apk 6.1.20261108` 逆向 + **德佟 P1 真机全量验证（2026-11-20）**
> + 官方指令文档 [DothanTech 位图打印命令说明](http://en.detonger.com/software/DothanTech-Bitmap%20Printing%20Command%20Description-2019-02-27.pdf)
> + npm 包 `lpapi-ble`（德佟官方 JS SDK，可见命令表与解析逻辑）
>
> 参考实现：[`p1_client.py`](p1_client.py)（可直接打印/查状态）、[`weida_protocol.py`](weida_protocol.py)（帧与解析）
>
> 标记：✅ 真机验证　⚠️ 推断　❓ 未解

---

## 0. 结论速览（P1 实测）

**设备**：`P1-61085930` / `28:D4:1E:9A:99:DB`
**型号** `PDBT33F-DF4`　**厂商** PingDong / 德佟电子　**固件** `5.20`　**打印头** 384 点 / 203dpi

### 0.1 连接与流控 ✅

```
服务 FF00
  FF02  write without response   ← 所有数据写这里，单片 20 字节
  FF03  notify                   ← 信用额度：收到 01 nn 表示 +nn 个额度，每写一片 -1
  FF01  notify                   ← 命令回包（0x1F 帧）从这里来
```

连上后固件先给 `01 07`（7 个额度）；额度用完必须等，否则丢数据。

### 0.2 帧格式 ✅

```
1F | CMD | LEN | DATA… | CRC
```

| 项 | 规则 |
|---|---|---|
| 帧头 | 主机→机、机→主机 **都是 0x1F**（另有固件用 0xAA/0xBB） |
| LEN | `<192` 一字节；否则 `(0xC0\|hi), lo` |
| CRC | `~(sum(CMD..DATA 含 LEN)) & 0xFF`，校验：全段求和 `== 0xFF` |
| 免校验 | CRC 位填 **`0x88`** |

实例：状态查询 `1F 70 00 8F`；设备名 `1F 79 00 86`。

### 0.3 命令表 ✅（来自官方 SDK `DzCommand`）

| 命令 | 值 | 方向 | 说明 |
|---|---|---|---|
| `CMD_IS_PRINTABLE` | **0x70** | 问 | 查状态，回 1 字节状态码 |
| `CMD_PRINTER_DPI` | 0x71 | 问 | 回 1 字节，203 |
| `CMD_PRINTER_WIDTH` | 0x72 | 问 | 回 `[0]=01, [1..2]=宽度点` |
| `CMD_MANUFACTURER` | 0x75 | 问 | GBK 字符串（"德佟电子\|DETONG"） |
| `CMD_DEVICE_NAME` | 0x79 | 问 | ASCII，如 `P1-61085930` |
| `CMD_DEVICE_VERSION` | 0x7A | 问 | 固件版本 |
| `CMD_BUFFER_SIZE` | 0x77 | 问 | 缓冲大小 |
| `CMD_ENABLE_SETTING` | 0x80 | 写 | 初始化：先 `[7F]`，结束再 `[80]` |
| `CMD_REQ_ADCVALUE` | **0x88** | 问 | `[1]`→电量　`[2]`→打印头温度 |
| `CMD_GAP_TYPE` | 0x42 | 写 | 纸张类型：0 连续 / 2 **不干胶** / 3 黑标 / 4 透明 |
| `CMD_GAP_LEN` | 0x45 | 写 | 间隙长度 |
| `CMD_DARKNESS` | 0x43 | 写 | 浓度 1..15 |
| `CMD_SPEED` | 0x44 | 写 | 速度 1..5 |
| `CMD_POSITIONING` | 0x5C | 问 | 定位（北斗/GPS，非走纸） |
| `CMD_PUSH_STATUS` | 0x40 | 推 | 电量/状态主动上报 |

### 0.4 状态码 ✅（`0x70` 回包首字节）

```
0 可打印   1 打印中   2 转马达   10 无任务   11 页面未收全   12 任务取消
20 环境未就绪   30 电压低   31 电压高   32 无打印头   33 打印头过热
34 开盖   35 缺纸   36 碳带盒未锁   37 无碳带   38 碳带不匹配
39 温度过低   40 碳带用完   41 色带用完   42 无标签纸   43 标签不匹配
44 标签用完   45 无色带   46 色带不匹配   50 标签盒未锁紧
```

### 0.5 电量 / 温度 ✅

```
发 1F 88 01 01   →  1F 88 13 01 01 88 01 87 01 87 01 87 00 00 10 41 ff 00 00 1e 0c 40 88
                     data[7..8] 大端 = 0x0187 = 391 → 3.91V
                     data[12] = 65 → 电量 65%
                     data[10] = 0 → 未充电

发 1F 88 01 02   →  1F 88 0a 02 00 d9 … → (0x00d9)/10 = 21.7°C
```

**前置条件**：连接后必须先发 `1F 80 01 7F`（开启设置），否则 0x88 无回包。

### 0.6 打印一张 40×30mm 标签 ✅

```python
0C                          # ① 先定位到标签边界（会退纸找间隙，等 1.5s）
1B 40                       # ② 初始化 + 开始一张标签
1F 27 01 28 88              # ③ 设宽度 40mm（n=毫米数）
1F 2A nL nH <row>           # ④ 逐行（320 点 → 40 字节）
...                         #    相同行可用 1F 2E n 压缩
0C                          # ⑤ 结束，定位到下一张边界
```

**实测**：先 `0C` 再打印，40×30 不干胶完整落在一张上（用户确认）；不打 `0C` 会跨标签。

### 0.7 还没解决 / 限制

| 项 | 情况 |
|---|---|
| 反向走纸命令 | `ESC j n` 无效，只有前进。`0C` 内部会自己退纸找边界，但我们没法单独控制 |
| "没检测到标签就退纸重试" | 做不到（无反向命令）；替代方案：**打印前先查状态**，42/35 就不打并提示 |
| 条码/文字原生命令 | 未知；稳妥做法是渲染成位图打印 |

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
