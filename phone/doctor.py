#!/usr/bin/env python3
"""
phone/doctor.py — 部署前自检（在 proot Ubuntu 里跑，不需要打印机）

    python3 phone/doctor.py                 # 默认查 8000 端口
    python3 phone/doctor.py --port 8080

逐项检查：Python 版本 / Pillow / 中文字体 / 目录完整性 / 端口占用 / 回环绑定 / 编码冒烟。
任何一项 FAIL 都会给出可直接照抄的修复命令。
"""
from __future__ import annotations

import argparse
import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"
rows: list[tuple[str, str, str]] = []


def add(level: str, name: str, detail: str = "") -> None:
    rows.append((level, name, detail))


def check_python() -> None:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 8):
        add(FAIL, "Python 版本", detail + "（需要 >= 3.8，apt install python3）")
    else:
        add(OK, "Python 版本", detail)


def check_pillow() -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
        import PIL
    except ImportError:
        add(FAIL, "Pillow", "未安装 → apt install python3-pil")
        return
    add(OK, "Pillow", PIL.__version__)
    # 真正画一次中文，确认能用
    try:
        img = Image.new("L", (120, 32), 255)
        ImageDraw.Draw(img).text((2, 2), "中文abc", fill=0)
        add(OK, "Pillow 绘制", "中文文本可渲染")
    except Exception as exc:                                    # noqa: BLE001
        add(FAIL, "Pillow 绘制", f"{type(exc).__name__}: {exc}")


def check_font() -> None:
    from memobird_printer.image import _DEFAULT_FONTS

    found = [p for p in _DEFAULT_FONTS if p and os.path.exists(p)]
    if found:
        add(OK, "中文字体", found[0])
    else:
        add(WARN, "中文字体", "没找到 CJK 字体 → 中文会打成方块；apt install fonts-noto-cjk")


def check_tree() -> None:
    need = ["web/index.html", "web/app.js", "web/style.css", "phone/serve.py", "memobird_printer/image.py"]
    missing = [p for p in need if not os.path.isfile(os.path.join(ROOT, p))]
    if missing:
        add(FAIL, "目录完整性", "缺少: " + ", ".join(missing) + " → 重新解压/ git clone")
    else:
        add(OK, "目录完整性", f"{len(need)} 个关键文件齐全")


def check_port(port: int) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
        add(OK, f"端口 {port}", "空闲")
    except OSError as exc:
        add(WARN, f"端口 {port}", f"被占用（{exc.strerror}）→ 换端口 --port 8080")
    finally:
        s.close()


def check_loopback() -> None:
    """确认能起一个监听 127.0.0.1 的服务 —— Chrome 只认 loopback 的安全上下文。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        c = socket.create_connection(("127.0.0.1", port), timeout=2)
        c.close()
        srv.close()
        add(OK, "回环监听", f"127.0.0.1:{port} 可绑可连")
    except OSError as exc:
        srv.close()
        add(FAIL, "回环监听", f"{exc}")


def check_encode() -> None:
    try:
        from memobird_printer import packet
        from memobird_printer.image import dither_to_raw, prepare, raw_to_bmp

        job = packet.job_for_text("自检 self-test")
        w, h, raw = dither_to_raw(prepare("自检"), "threshold")
        bmp = raw_to_bmp(w, h, raw, top_down=True)
        bmpjob = packet.build_bmp_job(bmp)
        add(OK, "编码冒烟", f"文本 {job.chunks} 帧 / 位图 {bmpjob.chunks} 帧（{w}×{h}）")
    except Exception as exc:                                    # noqa: BLE001
        add(FAIL, "编码冒烟", f"{type(exc).__name__}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    print("=" * 62)
    print(" memobird 手机端部署自检")
    print("=" * 62)
    check_python()
    check_pillow()
    check_font()
    check_tree()
    check_port(args.port)
    check_loopback()
    check_encode()

    for level, name, detail in rows:
        print(f" [{level}] {name:<12} {detail}")

    fails = sum(1 for r in rows if r[0] == FAIL)
    warns = sum(1 for r in rows if r[0] == WARN)
    print("-" * 62)
    if fails:
        print(f" {fails} 项必须修复（见上面 FAIL 行的命令），修完重跑本脚本。")
        return 1
    print(f" 通过{f'（{warns} 条提醒，不影响启动）' if warns else ''}。下一步：")
    print(f"   python3 phone/serve.py --port {args.port}")
    print(f"   手机 Chrome 打开 http://127.0.0.1:{args.port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
