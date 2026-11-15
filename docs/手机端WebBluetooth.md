# 手机端方案：Termux(proot Ubuntu) + Chrome Web Bluetooth

> **要动手部署请直接看 [`部署文档.md`](部署文档.md)** —— 那份是逐步操作 + 排错手册。
> 本文讲的是**为什么这么设计**：传输层选型、协议形态、以及各环节的取舍。

目标：**手机上跑 Python、开个网页，用网页控制蓝牙打印机**。不需要 root，不需要 BlueZ，
不需要动 App 的私有协议。

## 1. 为什么是 Web Bluetooth（而不是在 Termux 里直接开蓝牙）

| 方案 | 卡点 |
|---|---|
| Termux 里 `pip install bleak` | 需要访问 HCI 设备，Android 上要 root / 需要 BlueZ 运行，proot 里基本无解 |
| Termux 里 `socket.AF_BLUETOOTH` + RFCOMM | 同上，且要配对权限 |
| **Chrome 的 Web Bluetooth** | GATT 由浏览器进程完成，页面只要在**安全上下文**里；`127.0.0.1` 就算安全上下文 ✅ |

所以分工是：**Python 只做编码引擎**（渲染 / 抖动 / BMP / 打包成 AA 帧），
**Chrome 只做蓝牙搬运**（把 base64 还原成字节，写进特征值）。

```
手机 Chrome（页面 + Web Bluetooth）  ──fetch──▶  127.0.0.1:8000（Python/PIL）
            │                                          │
            └──────── GATT write ───────▶  打印机      └ 返回 frames(base64)
```

## 2. 为什么这台打印机一定有 BLE

有道打印机**有 iOS 版**（App Store 2019 上线），而 iOS 根本不给普通 App 用经典蓝牙 SPP ——
所以配套硬件必须走 BLE。GT1/GO/G4 这一脉也都是 BLE（GT1 还额外带 SPP 给 Android 用）。
结论：Chrome 的设备选择框里应该能扫到它。

## 3. 装环境（Termux）

```bash
pkg update && pkg install -y proot-distro
proot-distro install ubuntu
proot-distro login ubuntu

# —— 以下在 Ubuntu 里 ——
apt update && apt install -y python3 python3-pil
```

### 把项目放进手机（三选一）

```bash
# A. 手机能上网且你有仓库：直接 git clone 你自己的仓库
# B. 电脑起个临时服务，手机上用浏览器下载 zip（最简单）
#    电脑: python tools/make_phone_zip.py && python -m http.server 9000
#    手机: 浏览器打开 http://<电脑IP>:9000/ 下载 memobird_phone.zip 后解压
# C. adb push（开着 USB 调试）
#    adb push <项目目录> /sdcard/
#    然后 cp -r /sdcard/<项目目录名> ~
```

## 4. 启动

```bash
cd ~/memobird-pocket-printer
python3 phone/serve.py            # 或 bash phone/run.sh
```

看到 `打开： http://127.0.0.1:8000` 后，在**手机 Chrome** 打开这个地址。

> ⚠️ 必须用 `127.0.0.1` 或 `localhost`。用局域网 IP 打开的话 Chrome 认为不是安全上下文，
> `navigator.bluetooth` 直接不存在。

## 5. 使用流程

1. 点 **连接打印机** → 在 Chrome 弹窗里选你的打印机（名字可能是 `GT1-xxxx` / `Memobird` 之类）
2. **文字** 页签：输入文字 → `预览` 看效果 → `打印`
   * 默认走 **GBK 文本帧**：一行字只有几十字节，1 帧发完，最快
   * 有 GBK 编不了的字符（emoji 等）会自动退回位图模式
3. **图片** 页签：选图 → 调二值化 → `预览` → `打印`
   * 照片用 Floyd，线稿/文字截图用阈值
4. 第一次先在 **调试** 页打一张「打印校准图」，确认方向

## 6. 校准与排错（照这张表做，两分钟定死格式）

打印校准图后看纸面：

| 现象 | 原因 | 改法 |
|---|---|---|
| 图和预览**上下颠倒** | 行序反了 | 调试页勾选 `垂直翻转`，重打 |
| **全白** | 设备收的是裸位图而不是 BMP | 图片页把「传输」改成 `裸位图帧` |
| **糊成一团 / 缺失行** | 分片太大 | 调试页把「写入分片」调到 `20 B` |
| **只打出第一段** | 多帧之间发太快或没预热 | 调小分片 + 保留「预热包」 |
| **Chrome 弹窗里根本没有设备** | 不是 BLE 机型 / 定位权限没给 | 给 Chrome 开定位权限再扫；仍没有就是经典蓝牙款，见下 |
| **连上但找不到可写特征值** | 特征值不是 ff02 | 调试页点「探测 GATT」，把表格发我，我加映射 |
| **弹出即断开** | 已被 App 占用 | 先把手机上的有道打印机 App 杀掉（同一时间只能一个连着） |

> 经典蓝牙款兜底：Windows 上可以用同一套库的 SPP 后端（`--spp COM5`），
> 或用 `socket(AF_BTH, SOCK_STREAM, 0x0003)` 走 RFCOMM。

## 7. 性能预期

* 文字（GBK 帧）：1 帧，几十字节，**秒出**
* 图片 384×320：BMP ≈15 KB → 按 20 B/写 ≈ 800 次写，**约 10–20 秒**（正常现象）
* 想快：调试页把分片调到 64/128（不稳再退回来）

## 8. 换机型要改什么

* GATT 特征值：`web/app.js` 顶部 `CHR_WRITE` / `CHR_NOTIFY`，或调试页手填
* 帧格式：`memobird_printer/packet.py`（`build_frame` / TLV tag 表）
* 局域网机型：根本不需要这个网页，直接用 `python -m memobird_printer text ... --lan <ip>`
