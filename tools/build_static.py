#!/usr/bin/env python3
"""
tools/build_static.py — 把 web/ 打成**单文件**静态页（docs/index.html）

用途：挂 GitHub Pages，手机浏览器直接打开，**完全不需要服务端**（编码在浏览器里做）。

    python tools/build_static.py          # → docs/index.html

做的事：把 style.css / encoder.js / render.js / gbk.js / app.js 全部内联进一个 HTML，
        并设置 window.MB_STANDALONE = true。
注意：内联时必须把 JS 里出现的 `</script>` 转义，否则会提前截断 <script> 块。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
OUT = os.path.join(ROOT, "docs", "index.html")

CSS = ["style.css"]
JS = ["encoder.js", "render.js", "gbk.js", "app.js"]


def read(name: str) -> str:
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return f.read()


def safe_script(js: str) -> str:
    """避免内联脚本被 `</script>` 提前截断。"""
    return re.sub(r"</(script)", r"<\\/\1", js, flags=re.I)


def main() -> int:
    html = read("index.html")
    css = "\n".join(f"/* ==== {n} ==== */\n{read(n)}" for n in CSS)
    js_bundle = "\n".join(f"/* ==== {n} ==== */\n{read(n)}" for n in JS)

    # 1) 去掉外链 <link rel=stylesheet> 和 <script src=...>
    html = re.sub(r'\s*<link rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r'\s*<script src="[^"]*"></script>', "", html)

    # 2) 注入内联样式
    html = html.replace("</head>", f"<style>\n{css}\n</style>\n</head>")

    # 3) 注入内联脚本（先设标志位）
    banner = (
        "<script>window.MB_STANDALONE = true;</script>\n"
        "<script>\n" + safe_script(js_bundle) + "\n</script>\n"
    )
    html = html.replace("</body>", banner + "</body>")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    size = os.path.getsize(OUT)
    gz = len(__import__("gzip").compress(html.encode("utf-8"), 9))
    print(f"{OUT}")
    print(f"  {size / 1024:.0f} KB（gzip {gz / 1024:.0f} KB）")
    print(f"  内联：{', '.join(CSS + JS)}")
    if "</script>" in js_bundle.lower().replace("<\\/script", ""):
        print("  !! 仍有未转义的 </script>，检查一下", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
