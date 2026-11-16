#!/usr/bin/env python3
"""
tools/sync_vendor.py — 把 shared/web/ 的共享前端源码同步到各 app 的 vendor/

为什么要有这一步：两个网页实现要求**互不依赖、各自可单独部署**，
所以每个 app 目录里都放一份自己的 vendor/ 副本，而不是运行时去 ../shared 找文件。
共享源码只有一份（shared/web/），避免两处改漏。

    python tools/sync_vendor.py            # 同步
    python tools/sync_vendor.py --check    # 只检查是否一致（CI 用，不一致返回 1）
"""
from __future__ import annotations

import filecmp
import shutil
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(ROOT, "shared", "web")

# 每个实现需要哪些共享文件（顺序无关，只是清单）
VENDOR_MAP = {
    # 实现 2：编码在服务端，前端只要 BLE + UI
    os.path.join(ROOT, "apps", "web-server", "vendor"): [
        "style.css", "ble-util.js", "ble-link.js", "ui.js",
    ],
    # 实现 1：纯静态，前端要自带编码器 + GBK 码表 + canvas 渲染
    os.path.join(ROOT, "apps", "static-web", "vendor"): [
        "style.css", "ble-util.js", "ble-link.js", "ui.js",
        "encoder.js", "render.js", "gbk.js",
    ],
}


def main(argv: list[str]) -> int:
    check = "--check" in argv
    problems: list[str] = []

    for target, files in VENDOR_MAP.items():
        rel = os.path.relpath(target, ROOT)
        if not check:
            os.makedirs(target, exist_ok=True)
        for name in files:
            src = os.path.join(SHARED, name)
            dst = os.path.join(target, name)
            if not os.path.isfile(src):
                problems.append(f"缺少共享源共享文件: shared/web/{name}")
                continue
            if check:
                if not os.path.isfile(dst):
                    problems.append(f"{rel}/{name} 缺失")
                elif not filecmp.cmp(src, dst, shallow=False):
                    problems.append(f"{rel}/{name} 与 shared/web/{name} 不一致")
            else:
                shutil.copy2(src, dst)

    if check:
        if problems:
            print("vendor 与 shared/web 不一致：")
            for p in problems:
                print("  -", p)
            print("\n修法：python tools/sync_vendor.py")
            return 1
        print("vendor 全部与 shared/web 一致 ✅")
        return 0

    total = sum(len(v) for v in VENDOR_MAP.values())
    print(f"已同步 {total} 个文件到 {len(VENDOR_MAP)} 个 app 的 vendor/")
    for target, files in VENDOR_MAP.items():
        print(f"  {os.path.relpath(target, ROOT)}: {', '.join(files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
