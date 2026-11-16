# 实现 1：纯静态网页（零后端）

浏览器里完成**全部**工作：渲染、抖动、BMP 封装、GBK 编码、蓝牙传输。
不需要 Python 服务、不需要 Termux、不发起任何网络请求 —— 只要一个 https 页面。

```
apps/static-web/
├── index.html       页面骨架（开发时直接用）
├── app.js           本实现专属 UI/编码调度
├── build.py         打成单文件 → ../../docs/index.html
└── vendor/          共享前端（由 tools/sync_vendor.py 同步，勿手改）
    ├── ble-util.js  GATT 选择/回包解析
    ├── ble-link.js  BLE 连接与写入
    ├── ui.js        日志/页签/进度
    ├── encoder.js   帧/TLV/抖动/BMP（与 Python 实现逐字节一致）
    ├── render.js    canvas 渲染文字/图片/校准图
    ├── gbk.js       GBK 码表（21791 码位）
    └── style.css
```

## 用在哪

| 场景 | 做法 |
|---|---|
| 手机上直接用 | 打开 Pages 地址或本地静态服务 → 「连接打印机」 |
| 分享给别人 | GitHub Pages（下面） |
| 改代码调试 | `python -m http.server 8000 --directory apps/static-web` → `http://127.0.0.1:8000` |

> **必须是安全上下文**：`https://` 或 `http://localhost`（含 127.0.0.1）。
> 用 `file://` 双击打开、或用局域网 IP 打开，`navigator.bluetooth` 直接不存在。

## 构建单文件

```bash
python tools/sync_vendor.py            # 先把 shared/web 同步进 vendor/
python apps/static-web/build.py        # → docs/index.html（约 133 KB，gzip 67 KB）
```

产物自包含：CSS + 7 个 JS（含 79 KB GBK 码表）全部内联，零外链。

## 部署到 GitHub Pages

1. 仓库 → **Settings** → **Pages**
2. Source 选 *Deploy from a branch*
3. Branch 选 `main`，目录选 **`/docs`** → Save
4. 等 1 分钟，访问 `https://<用户名>.github.io/<仓库名>/`

`docs/` 里同时放着协议/逆向文档，所以 Pages 站点会顺带把文档也发布出去（都是公开内容）。

## 这个实现的能力边界

| 项 | 说明 |
|---|---|
| 文字 | 默认 GBK 文本帧（1 帧几十字节，最快）；调字号/浓度自动转位图 |
| 字号 | 位图模式下精确到像素；GBK 帧只有固件档位（GT1 实测无效） |
| 浓度 | 4 档（阈值偏移 + 笔画膨化），位图模式下生效 |
| 图片 | canvas 缩放到 384 宽 + 抖动，质量略逊 Pillow 的 LANCZOS（实际差别不大） |
| 离线 | 首次加载后缓存即可离线；打印内容不出网 |
| 依赖 | 无。真的没有 —— 不装 Python、不装 node |

## 与实现 2 的区别（一句话）

**实现 1 把编码器搬进了浏览器**（多下载 ~130 KB，换来零后端）；
**实现 2 把编码器留在 Python**（页面只要 ~20 KB，但要跑一个本地服务）。

两者共用 `shared/web/` 里的 BLE 与编码代码，所以行为一致 —— 包括 GBK 帧、BMP 格式、
浓度档位、校准图这些容易踩坑的地方。

## 排错

- 页面能开但 `navigator.bluetooth` 不存在 → 不是 https/localhost
- 弹窗里没设备 → 给 Chrome 定位/附近设备权限；杀掉官方 App
- 打印结果不对 → 打「校准图」，对照 [`../../docs/手机端WebBluetooth.md`](../../docs/手机端WebBluetooth.md) 的判定表
