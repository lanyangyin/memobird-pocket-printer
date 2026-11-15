#!/usr/bin/env python3
"""
tools/make_phone_zip.py — 打一个「手机端最小包」，方便 Termux 里解压即用

    python tools/make_phone_zip.py            # → memobird_phone.zip（默认）

内含：memobird_printer/ web/ phone/ docs/ + README.md + requirements.txt
不含：APK、反编译产物、演示图。
"""
from __future__ import annotations

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = ["memobird_printer", "web", "phone", "docs"]
FILES = ["README.md", "requirements.txt", "LICENSE"]


def main(out: str | None = None) -> int:
    out = out or os.path.join(ROOT, "memobird_phone.zip")
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for d in DIRS:
            base = os.path.join(ROOT, d)
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [x for x in dirnames if x != "__pycache__"]
                for fn in filenames:
                    if fn.endswith((".pyc", ".zip")):
                        continue
                    p = os.path.join(dirpath, fn)
                    z.write(p, os.path.relpath(p, ROOT))
                    count += 1
        for f in FILES:
            p = os.path.join(ROOT, f)
            if os.path.isfile(p):
                z.write(p, f)
                count += 1
    size = os.path.getsize(out) / 1024
    print(f"{count} 个文件 → {out}（{size:.0f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
