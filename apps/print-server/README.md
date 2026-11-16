# 实现 3：真正的打印服务（Python 直连 + HTTP API）

前两个实现里**蓝牙在浏览器**手里；这个实现里**蓝牙在 Python 进程**手里：
它自己连打印机、自己发字节，对外只暴露 HTTP。所以它必须跑在有蓝牙适配器的机器上
（PC / 树莓派 / NAS），好处是**任何东西都能打印** —— 脚本、cron、Home Assistant、手机浏览器。

```
apps/print-server/
├── server.py     HTTP 服务 + 三种传输后端 + 编码
├── client.py     命令行客户端（text / image / status）
└── README.md
```

## 三种后端

| 后端 | 目标 | 适用 |
|---|---|---|
| `ble` | `--target AA:BB:CC:DD:EE:FF` | BLE 机型（GT1/GO/G4/有道口袋打印机），Win10+ / Linux / macOS |
| `spp` | `--target COM5` 或 `/dev/rfcomm0` | 经典蓝牙 SPP（Windows 配对后是 COM 口，Linux 先 `rfcomm bind`） |
| `lan` | `--target 192.168.1.50` | WiFi 机型（走 `http://<ip>/sys/printer`） |
| `fake` | 无需目标 | 不接硬件，只生成帧 —— 演练 / CI / 看协议 |

## 安装与启动

```bash
pip install pillow bleak pyserial          # bleak 仅 ble 后端需要；pyserial 仅 spp 需要

# BLE
python apps/print-server/server.py --backend ble --target AA:BB:CC:DD:EE:FF --port 8100

# 经典蓝牙（Windows 里配对后设备管理器能看到 "Standard Serial over Bluetooth link (COM5)"）
python apps/print-server/server.py --backend spp --target COM5 --port 8100

# WiFi 机型
python apps/print-server/server.py --backend lan --target 192.168.1.50 --port 8100

# 不接硬件，先看看能生成什么
python apps/print-server/server.py --backend fake --port 8100 --verbose
```

启动后：

* 浏览器开 `http://127.0.0.1:8100/` 有个最小输入框，可以直接打
* 或走 API（下面）

## API

### `GET /health`

```json
{"ok": true, "version": "1.0.0", "backend": "ble", "target": "AA:BB:..."}
```

### `GET /status`

```json
{"backend": "ble", "printed": 3, "last": {"at": "2026-11-16 23:20:01",
 "meta": {"format": "gbk", "chunks": 1, "bytes": 15}, "elapsed_ms": 2},
 "last_error": null}
```

### `GET /device`

读打印机自身信息（仅 BLE 后端，走厂商协议 `cmd 0x01`）：

```json
{"ok": true, "backend": "ble", "target": "00:15:83:E4:7A:F2",
 "device": {"cmd": "0x01", "serial": "636404963750000000",
            "fields": {"0x01": {"label": "电量% / 温度℃?", "int": 23, "confirmed": false},
                       "0x03": {"label": "指示灯", "int": 0, "confirmed": true}}}}
```

字段语义与"哪些已证实"见 [`../../docs/协议说明.md`](../../docs/协议说明.md) 第 1.7 节。

### `POST /print`（也可以 `/print/text`、`/print/image`）

```json
{
  "text": "服务器磁盘 85%",        // 或者 "image": "data:image/png;base64,..."
  "kind": "text",                  // 可省：有 image 就按图片，否则按文字
  "darken": 1,                     // 0..3 浓度档位
  "fontSize": 26,                  // 像素；>26 自动走位图
  "bold": false, "underline": false,
  "mode": "threshold",             // floyd | atkinson | bayer | threshold
  "feed": true,                    // 打后走纸（默认 true）
  "vflip": false, "preheat": true
}
```

返回：

```json
{"ok": true, "meta": {"format": "gbk", "chunks": 1, "bytes": 15,
 "width": 384, "height": 0}, "elapsed_ms": 2, "frames": 2, "bytes_sent": 2126}
```

错误：`400` 参数问题（如空文本）、`401` API key 不对、`503` 蓝牙层失败（消息里带原因）。

### 认证（可选）

```bash
python apps/print-server/server.py --backend ble --target ... --api-key SECRET
# 或 MEMOBIRD_API_KEY=SECRET
curl -X POST http://nas:8100/print -H 'X-Api-Key: SECRET' -d '{"text":"hi"}'
```

## 客户端

```bash
# 命令行（自带）
python apps/print-server/client.py text "服务器磁盘 85%" --darken 1
python apps/print-server/client.py image photo.jpg --mode floyd
python apps/print-server/client.py status
python apps/print-server/client.py --url http://nas:8100 --key SECRET text "hi"

# curl
curl -X POST http://127.0.0.1:8100/print -H 'Content-Type: application/json' \
     -d '{"text":"hello"}'

# Python
import requests
requests.post("http://127.0.0.1:8100/print", json={"text": "备份完成", "darken": 1})

# cron：每天 9 点打一张待办
0 9 * * * curl -s -X POST http://127.0.0.1:8100/print -d '{"text":"今天要做的事"}'
```

## 常驻（Linux / 树莓派）

`/etc/systemd/system/memobird-print.service`：

```ini
[Unit]
Description=Memobird print server
After=bluetooth.target network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/memobird/apps/print-server/server.py \
          --backend ble --target AA:BB:CC:DD:EE:FF --host 0.0.0.0 --port 8100
Restart=always
RestartSec=5
User=pi

[Install]
WantedBy=multi-user.target
```

> 想对局域网开放就把 `--host` 改成 `0.0.0.0`，**并一定配 `--api-key`**。
> 这个端口没有任何别的鉴权。

Windows 上可以用「任务计划程序」+ `pythonw.exe`，或者 `nssm`。

## 实现细节（为什么这么写）

* **BLE 在 asyncio 里**：bleak 是 async 的，而 `http.server` 是同步的。
  所以服务起了一个常驻事件循环线程，HTTP 线程把协程 `run_coroutine_threadsafe` 投进去。
* **每个任务单独连接**：BLE 连接不稳定，长连接反而更难维护；一次打印 1~2 秒的连接成本可以接受。
* **串行执行**：内部一把 `threading.Lock`，两次打印不会交织（硬件只有一个缓冲区）。
* **编码复用共用库**：和实现 2 完全同一套 `build_frames` 逻辑，所以文本走 GBK 帧、
  调字号/浓度自动转位图、BMP 用官方格式 —— 行为一致。

## 已知限制

* `lan` 后端目前只做文本/图片，不做多包大图（26 KB 以上的 body 会被固件拒）。
* 服务端只支持一个目标打印机（`--target` 一个）。要多台就起多个实例、换端口。
* BLE 断开后不会自动重连；下一个请求会重新连接（失败会返回 503 和原因）。
