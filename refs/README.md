# refs/ — 第三方参考实现（只读，不参与构建）

放这里的文件**不是本项目的代码**，只是逆向比对用的参考，运行时不会 import 它们。

| 文件 | 来源 | 许可 | 用途 |
|---|---|---|---|
| `gt1_memobird_driver.py` | [5uX1a0ma0/memobird-gt1-mcp](https://github.com/5uX1a0ma0/memobird-gt1-mcp) | MIT | GT1 经典蓝牙（SPP）驱动，逆向官方 Android SDK 得到。用来校准 BMP 编码、TLV tag 顺序、文本分包 |
| `gt1_README.md` | 同上 | MIT | 原文协议说明（帧格式、tag 语义、预热、图像方向坑） |

## 它帮我们修掉的三个真机问题

1. **BMP 编码**：`biHeight` 取正 + 数据行序 top-down + 调色板 index0=黑/1=白（行数据取反）。
   我们原来写负高度 + 调色板反序 + bit=1 为黑，固件判无效，打出自带的示范页
   `nice to meet you`。
2. **字号/样式 tag**：文本帧必须带 `0x0D`(加粗) / `0x11`(下划线) / `0x10`(字号档位)，
   否则字号不生效、甚至解析错位。
3. **文本分包**：每包 ≤300 字节（官方 SDK 值）。

改动落在 `memobird_printer/`（Python）与 `web/encoder.js`（JS），
两边输出由 `tests/test_encoder_js.js` 逐字节校验。
