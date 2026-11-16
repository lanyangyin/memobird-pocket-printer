#!/usr/bin/env python3
"""
tools/gen_gbk_table.py — 生成浏览器用的 GBK 编码表（web/gbk.js）

为什么需要：JS 的 TextEncoder 只会 UTF-8，而打印机的**文本帧要求 GBK**。
纯静态网页（没有 Python 服务端）要保住"文字走 GBK 帧"这条快路径，就得自带码表。

设计（为什么只有一张字符串）：
  GBK 双字节区是 (b1 0x81–0xFE) × (b2 0x40–0xFE) 的固定网格，
  所以只要按这个顺序把每个码位对应的字符排成一个字符串，
  浏览器端再按同样的顺序走一遍网格，就能**重建出码值**，不用再存第二张表。
  无效码位填 U+0000 占位。

  码值 0x81xx–0xFExx 里有一部分正好落在 UTF-16 代理区（0xD800–0xDFFF），
  不能直接塞进字符串；这也是"存字符、重建码值"比"存码值"更稳的原因。

    python tools/gen_gbk_table.py         # → web/gbk.js
"""
from __future__ import annotations

import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "shared", "web", "gbk.js")

B1_START, B1_END = 0x81, 0xFE
B2_START, B2_END = 0x40, 0xFE
SLOTS = (B1_END - B1_START + 1) * (B2_END - B2_START + 1)   # 126 × 191 = 24066


def build() -> tuple[str, int]:
    chars: list[str] = []
    valid = 0
    for b1 in range(B1_START, B1_END + 1):
        for b2 in range(B2_START, B2_END + 1):
            try:
                ch = bytes([b1, b2]).decode("gbk")
            except UnicodeDecodeError:
                chars.append("\x00")
                continue
            if len(ch) != 1:
                chars.append("\x00")
                continue
            chars.append(ch)
            valid += 1
    assert len(chars) == SLOTS, (len(chars), SLOTS)
    return "".join(chars), valid


def js_literal(s: str) -> str:
    """JSON 转义（安全）+ 避免 `</script>` 截断内联 HTML。"""
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


def main() -> int:
    table, valid = build()
    body = f"""/* web/gbk.js — 自动生成，别手改（tools/gen_gbk_table.py）
 *
 * GBK 双字节码表：网格 {SLOTS} 格，其中 {valid} 个有效码位。
 * 用法：GBK.encode(str) → Uint8Array；含 GBK 无法表示的字符时返回 null。
 *
 * 表里每个字符对应网格 (b1 = 0x{B1_START:02X}..0x{B1_END:02X}, b2 = 0x{B2_START:02X}..0x{B2_END:02X}) 的
 * 一个位置，\\u0000 表示该码位无定义。码值在浏览器端按同样顺序重建。
 */
(function (root, factory) {{
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GBK = api;
}})(typeof globalThis !== 'undefined' ? globalThis : this, function () {{
  'use strict';

  const TABLE = {js_literal(table)};
  const B1_START = 0x{B1_START:02x}, B1_END = 0x{B1_END:02x};
  const B2_START = 0x{B2_START:02x}, B2_END = 0x{B2_END:02x};

  let map = null;
  function table() {{
    if (map) return map;
    map = new Map();
    map.set('\\u20AC', 0x80);            // cp936 把 0x80 映射成欧元符号
    let i = 0;
    for (let b1 = B1_START; b1 <= B1_END; b1++) {{
      for (let b2 = B2_START; b2 <= B2_END; b2++, i++) {{
        const ch = TABLE[i];
        if (ch !== '\\u0000') map.set(ch, (b1 << 8) | b2);
      }}
    }}
    return map;
  }}

  /** 字符串 → GBK 字节；含 GBK 无法表示的字符时返回 null */
  function encode(str) {{
    const t = table();
    const out = [];
    for (const ch of str) {{
      const cp = ch.codePointAt(0);
      if (cp < 0x80) {{ out.push(cp); continue; }}
      const code = t.get(ch);
      if (code === undefined) return null;
      out.push(code >> 8, code & 0xff);
    }}
    return Uint8Array.from(out);
  }}

  /** GBK 字节 → 字符串（调试用） */
  function decode(bytes) {{
    const t = table();
    const rev = new Map();
    for (const [ch, code] of t) rev.set(code, ch);
    let s = '';
    for (let i = 0; i < bytes.length; i++) {{
      const b = bytes[i];
      if (b < 0x80) {{ s += String.fromCharCode(b); continue; }}
      const code = (b << 8) | (bytes[++i] ?? 0);
      s += rev.get(code) ?? '\\uFFFD';
    }}
    return s;
  }}

  return {{ encode, decode, valid: {valid} }};
}});
"""
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    size = os.path.getsize(OUT)
    raw = body.encode("utf-8")
    print(f"{OUT}")
    print(f"  网格 {SLOTS} 格 / 有效 {valid} 码位")
    print(f"  文件 {size / 1024:.0f} KB（UTF-8 {len(raw) / 1024:.0f} KB，gzip "
          f"{len(zlib.compress(raw, 9)) / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
