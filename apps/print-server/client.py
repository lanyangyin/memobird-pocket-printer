#!/usr/bin/env python3
"""
apps/print-server/client.py — 打印服务的命令行客户端

    python apps/print-server/client.py text "服务器磁盘 85%" --darken 1
    python apps/print-server/client.py image photo.jpg --mode floyd
    python apps/print-server/client.py status
    python apps/print-server/client.py text "hi" --url http://nas:8100 --key SECRET
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import urllib.request


def post(url: str, body: dict, key: str | None, timeout: float) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    if key:
        req.add_header("X-Api-Key", key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def get(url: str, key: str | None, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if key:
        req.add_header("X-Api-Key", key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main(argv=None) -> int:
    # 注意：parents 里的 default 会被子命令的默认值覆盖（argparse 的老坑），
    # 所以用 SUPPRESS，解析后再做兜底。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", default=argparse.SUPPRESS)
    common.add_argument("--key", default=argparse.SUPPRESS)
    common.add_argument("--timeout", type=float, default=argparse.SUPPRESS)

    ap = argparse.ArgumentParser(description="打印服务客户端", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("text", help="打印文字", parents=[common])
    t.add_argument("text")
    t.add_argument("--darken", type=int, default=0, choices=[0, 1, 2, 3])
    t.add_argument("--font-size", type=int, default=26)
    t.add_argument("--bold", action="store_true")
    t.add_argument("--underline", action="store_true")
    t.add_argument("--no-feed", action="store_true", help="打印后不走纸")

    i = sub.add_parser("image", help="打印图片", parents=[common])
    i.add_argument("path")
    i.add_argument("--mode", default="floyd", choices=["floyd", "atkinson", "bayer", "threshold"])
    i.add_argument("--darken", type=int, default=0, choices=[0, 1, 2, 3])
    i.add_argument("--no-feed", action="store_true")

    sub.add_parser("status", help="查询服务状态", parents=[common])

    args = ap.parse_args(argv)
    url = getattr(args, "url", None) or "http://127.0.0.1:8100"
    key = getattr(args, "key", None) or os.environ.get("MEMOBIRD_API_KEY")
    timeout = getattr(args, "timeout", None) or 180.0
    base = url.rstrip("/")

    try:
        if args.cmd == "status":
            print(json.dumps(get(base + "/status", key, timeout),
                             ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "text":
            body = {"text": args.text, "darken": args.darken, "fontSize": args.font_size,
                    "bold": args.bold, "underline": args.underline, "feed": not args.no_feed}
        else:
            with open(args.path, "rb") as f:
                raw = f.read()
            mime = mimetypes.guess_type(args.path)[0] or "image/png"
            body = {"image": f"data:{mime};base64," + base64.b64encode(raw).decode(),
                    "mode": args.mode, "darken": args.darken, "feed": not args.no_feed}

        out = post(base + "/print", body, key, timeout)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}", file=sys.stderr)
        return 1
    except Exception as exc:                                        # noqa: BLE001
        print(f"失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
