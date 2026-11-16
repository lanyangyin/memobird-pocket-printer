#!/usr/bin/env python3
"""
tools/make_bundle.py — 把某个实现打成可直接传到手机上用的 zip

    python tools/make_bundle.py --target web-server     # → dist/memobird-web-server.zip
    python tools/make_bundle.py --target print-server   # → dist/memobird-print-server.zip
    python tools/make_bundle.py --target static-web     # → dist/memobird-static-web.zip

每个实现都是自包含的：带上它自己的目录（含 vendor/）、共用库 memobird_printer/、
requirements.txt 与 LICENSE —— 解压即用，不需要另一份代码。
"""
from __future__ import annotations

import argparse
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TARGETS = {
    "web-server": {
        "dirs": ["apps/web-server", "memobird_printer"],
        "files": ["requirements.txt", "LICENSE"],
    },
    "print-server": {
        "dirs": ["apps/print-server", "memobird_printer"],
        "files": ["requirements.txt", "LICENSE"],
    },
    "static-web": {
        "dirs": ["apps/static-web"],
        "files": ["LICENSE"],
    },
}

SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}
SKIP_EXT = {".pyc", ".zip"}


def add_tree(zf: zipfile.ZipFile, rel: str, count: list[int]) -> None:
    base = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.isdir(base):
        raise FileNotFoundError(rel)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1] in SKIP_EXT:
                continue
            p = os.path.join(dirpath, fn)
            zf.write(p, os.path.relpath(p, ROOT))
            count[0] += 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=sorted(TARGETS))
    ap.add_argument("-o", "--out", default="")
    args = ap.parse_args(argv)

    spec = TARGETS[args.target]
    out = args.out or os.path.join(ROOT, "dist", f"memobird-{args.target}.zip")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    count = [0]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in spec["dirs"]:
            add_tree(zf, d, count)
        for f in spec["files"]:
            p = os.path.join(ROOT, f)
            if os.path.isfile(p):
                zf.write(p, f)
                count[0] += 1

    size = os.path.getsize(out) / 1024
    print(f"{out}")
    print(f"  {count[0]} 个文件，{size:.0f} KB，包含：{', '.join(spec['dirs'] + spec['files'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
