#!/usr/bin/env python3
"""
apps/static-web/build.py — 把静态版打成**单文件** HTML（实现 1 的交付物）

    python tools/sync_vendor.py                 # 先把 shared/web 同步到 vendor/
    python apps/static-web/build.py             # → docs/index.html（GitHub Pages 入口）
    python apps/static-web/build.py -o page.html

产物自包含：style.css + 全部 JS（含 79KB 的 GBK 码表）内联，零外链、零后端。
内联时必须转义 JS 里出现的 `</script>`，否则会提前截断脚本块。
"""
from __future__ import annotations

import argparse
import gzip
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(APP))
VENDOR = os.path.join(APP, "vendor")

# 顺序即依赖顺序
JS_ORDER = ["ble-util.js", "ble-link.js", "ui.js", "encoder.js", "render.js", "gbk.js"]
CSS_ORDER = ["style.css"]


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def safe_script(js: str) -> str:
    return re.sub(r"</(script)", r"<\\/\1", js, flags=re.I)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, "docs", "index.html"))
    args = ap.parse_args(argv)

    missing = [n for n in JS_ORDER + CSS_ORDER if not os.path.isfile(os.path.join(VENDOR, n))]
    missing += [n for n in ("app.js", "index.html") if not os.path.isfile(os.path.join(APP, n))]
    if missing:
        print("缺文件：" + ", ".join(missing))
        if any(n in JS_ORDER + CSS_ORDER for n in missing):
            print("先跑：python tools/sync_vendor.py")
        return 1

    html = read(os.path.join(APP, "index.html"))
    css = "\n".join(f"/* ==== {n} ==== */\n{read(os.path.join(VENDOR, n))}" for n in CSS_ORDER)
    js = "\n".join(f"/* ==== {n} ==== */\n{read(os.path.join(VENDOR, n))}" for n in JS_ORDER)
    js += "\n/* ==== app.js ==== */\n" + read(os.path.join(APP, "app.js"))

    # 去掉外链，注入内联
    html = re.sub(r'\s*<link rel="stylesheet"[^>]*>', "", html)
    html = re.sub(r'\s*<script src="[^"]*"></script>', "", html)
    html = html.replace("</head>", f"<style>\n{css}\n</style>\n</head>")
    # 版本号：静态页读库版本 + 前端版本，写进页面标题栏
    STATIC_VERSION = "1.3.3"
    banner = "<script>window.MB_STANDALONE = true;</script>\n<script>\n" + safe_script(js) + "\n</script>\n"
    html = html.replace("</body>", banner + "</body>")
    # 最后统一替换版本占位符（HTML 和 app.js 里的都要换）
    html = html.replace("__STATIC_VER__", STATIC_VERSION)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    size = os.path.getsize(args.out)
    gz = len(gzip.compress(html.encode("utf-8"), 9))
    print(f"{args.out}")
    print(f"  {size / 1024:.0f} KB（gzip {gz / 1024:.0f} KB）")
    print(f"  内联：{', '.join(CSS_ORDER + JS_ORDER + ['app.js'])}")
    if re.search(r'<script src=|<link rel="stylesheet"', html):
        print("  !! 仍有外链残留", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
