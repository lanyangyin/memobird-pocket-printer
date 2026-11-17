#!/usr/bin/env python3
"""
tests/test_live_full.py — 真机完整测试（CLI + 打印服务 HTTP）

按用户要求：**每打一次之前先查纸**，没纸立即停下等人换纸。

    python tests/test_live_full.py [--address 00:15:83:E4:7A:F2] [--no-http]

阶段：
  A. 设备在线与状态（info / 电量 / 缺纸 / 浓度）
  B. CLI 路径：feed / 文本(ASCII) / 文本(中文→位图) / 小图 / 分页大图 / 纸总长
  C. 打印服务 HTTP：health / status / device / led / feed / print(text, image, totalMm) / jobs
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from memobird_printer import device, packet          # noqa: E402
from memobird_printer.ble import BlePrinter          # noqa: E402

SERVER = os.path.join(ROOT, "apps", "print-server", "server.py")
CAL60 = os.path.join(ROOT, "tools", "calibration", "cal60.png")
SMALL = os.path.join(ROOT, "tools", "calibration", "small96.png")

passes = 0
fails: list[str] = []
stopped: str | None = None


def check(name: str, ok: bool, detail: str = "") -> bool:
    global passes
    if ok:
        passes += 1
        print(f"  [OK ] {name}{('  ' + detail) if detail else ''}", flush=True)
    else:
        fails.append(name)
        print(f"  [FAIL] {name}{('  ' + detail) if detail else ''}", flush=True)
    return ok


# --------------------------------------------------------------------------- #
async def read_status(address: str, attempts: int = 3):
    """读状态；设备忙/刚断开时偶发 Not connected，重连重试"""
    last = None
    for i in range(attempts):
        try:
            async with BlePrinter(address, echo=False) as b:
                infos, _ = await b.read_device_info(wait=1.6)
                if infos:
                    return infos[-1]
        except Exception as exc:                     # noqa: BLE001
            last = exc
            await asyncio.sleep(1.0 + i)
    if last:
        print(f"     (读状态重试 {attempts} 次仍失败：{type(last).__name__})", flush=True)
    return None


def paper_state(address: str):
    info = asyncio.run(read_status(address))
    if info is None:
        return None, None
    return device.paper_out(info), info


def need_paper(address: str, label: str) -> bool:
    """打印前查纸；没纸就记下停止原因"""
    global stopped
    time.sleep(0.8)
    paper, info = paper_state(address)
    if info is None:
        stopped = f"{label}：设备连不上（可能休眠）"
        print(f"  ⏸  {stopped} —— 停下", flush=True)
        return False
    if paper is True:
        stopped = f"{label}：缺纸"
        print(f"  ⏸  {stopped} —— 停下等你换纸", flush=True)
        return False
    return True


def run_cli(args: list[str], timeout: float = 180) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-m", "memobird_printer", *args], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# --------------------------------------------------------------------------- #
def phase_a(address: str):
    print("\n=== A) 设备状态 ===", flush=True)
    paper, info = paper_state(address)
    if info is None:
        time.sleep(2)
        paper, info = paper_state(address)
    if info is None:
        stopped = "设备连不上"
        print("  ⏸  设备连不上 —— 停下", flush=True)
        return False
    volt = device.battery_voltage(info)
    pct = device.battery_percent(info)
    check("序列号", bool(info.serial), str(info.serial))
    check("缺纸标志可读", paper is not None, f"paper_out={paper}")
    check("电压/电量可读", volt is not None, f"{volt}V ≈ {pct}%")
    dens = info.value(0x02)
    check("浓度可读", dens is not None, f"0x02={dens}")
    print(f"  纸：{'有' if paper is False else ('缺' if paper is True else '未知')}", flush=True)
    return paper is not True


def phase_b(address: str):
    print("\n=== B) CLI 路径 ===", flush=True)

    rc, out = run_cli(["info", "--ble", address, "--wait", "1.5"])
    check("info 命令", rc == 0 and "序列号" in out)

    if not need_paper(address, "CLI 走纸"):
        return
    rc, out = run_cli(["feed", "--mm", "10", "--total", "--tick", "--ble", address])
    check("feed 10mm（纸总长）", rc == 0 and "走纸" in out)

    if not need_paper(address, "CLI ASCII 文本"):
        return
    rc, out = run_cli(["text", "LIVE TEST A1", "--ble", address])
    check("文本 ASCII（GBK 帧）", rc == 0 and "已发送" in out)

    if not need_paper(address, "CLI 中文文本"):
        return
    rc, out = run_cli(["text", "中文实时测试", "--ble", address])
    check("文本 中文 → 位图", rc == 0 and "已发送" in out and "位图" in out)

    if not need_paper(address, "CLI 小图"):
        return
    rc, out = run_cli(["image", "tools/calibration/small96.png", "--ble", address])
    check("小图 small96（5 帧）", rc == 0 and "已发送" in out)

    if not need_paper(address, "CLI 分页大图"):
        return
    rc, out = run_cli(["image", "tools/calibration/cal60.png", "--ble", address, "--density", "6"])
    check("大图 cal60 → 自动分 2 页", rc == 0 and "分 2 页" in out, out.strip().splitlines()[-1] if out.strip() else "")

    if not need_paper(address, "CLI 纸总长"):
        return
    rc, out = run_cli(["text", "L=30", "--total-mm", "30", "--ble", address])
    check("纸总长 30mm", rc == 0 and "纸总长" in out)


# --------------------------------------------------------------------------- #
class Client:
    def __init__(self, base: str):
        self.base = base

    def req(self, method: str, path: str, body=None, timeout: float = 180):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {}


def phase_c(address: str):
    print("\n=== C) 打印服务 HTTP ===", flush=True)
    port = 8141
    srv = subprocess.Popen([sys.executable, SERVER, "--backend", "ble", "--target", address,
                            "--port", str(port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        c = Client(base)
        for _ in range(40):
            time.sleep(0.25)
            try:
                st, _ = c.req("GET", "/health", timeout=3)
                if st == 200:
                    break
            except Exception:
                continue

        st, body = c.req("GET", "/health", timeout=10)
        check("GET /health", st == 200 and body.get("ok") is True, str(body.get("version")))

        st, body = c.req("GET", "/status", timeout=10)
        check("GET /status", st == 200 and body.get("backend") == "ble")

        st, body = c.req("GET", "/device", timeout=60)
        check("GET /device（含电量/缺纸）", st == 200 and body.get("ok") is True,
              json.dumps({k: body.get(k) for k in ("paper_out", "battery")}, ensure_ascii=False)[:110])

        if body.get("paper_out") is True:
            print("  ⏸  缺纸 —— 后面的打印全部跳过", flush=True)
            global stopped
            stopped = "打印服务阶段：缺纸"
            return

        st, body = c.req("POST", "/device/led", {"on": True}, timeout=60)
        check("POST /device/led 开灯", st == 200 and body.get("led") == 1)
        st, body = c.req("POST", "/device/led", {"on": True}, timeout=60)
        check("POST /device/led 幂等", st == 200 and body.get("ok") is True)

        # 注意：固件每个任务固定多喂 18mm，所以"出 10mm 纸"物理上不可能（最少约 19mm）
        st, body = c.req("POST", "/feed", {"mm": 30}, timeout=120)
        check("POST /feed 30mm（纸总长）", st == 200 and body.get("meta", {}).get("dots") == 96,
              str(body.get("meta", {}).get("dots")))
        st, body = c.req("POST", "/feed", {"mm": 10}, timeout=120)
        check("POST /feed 10mm 给出最小说明", st == 200 and "最小出纸" in (body.get("meta", {}).get("note") or ""),
              (body.get("meta", {}).get("note") or "")[:40])

        st, body = c.req("POST", "/print", {"text": "HTTP TEXT OK", "checkPaper": True}, timeout=180)
        check("POST /print 文本（含缺纸预检）", st == 200 and body.get("ok") is True, str(st))

        st, body = c.req("POST", "/print", {"text": "中文 HTTP 测试", "checkPaper": True}, timeout=180)
        check("POST /print 中文（位图）", st == 200 and body.get("ok") is True, str(st))

        with open(CAL60, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        st, body = c.req("POST", "/print", {"image": b64, "checkPaper": True}, timeout=300)
        check("POST /print 大图（自动分页）", st == 200 and body.get("ok") is True, str(st))

        st, body = c.req("POST", "/print", {"text": "TOTAL 30", "totalMm": 30, "checkPaper": True}, timeout=180)
        check("POST /print 纸总长 30mm", st == 200 and body.get("ok") is True, str(st))

        # 定时任务：2 秒后打
        st, body = c.req("POST", "/jobs", {"text": "JOB OK", "delaySec": 2}, timeout=30)
        job_id = (body.get("job") or {}).get("id")
        check("POST /jobs 入队", st == 201 and bool(job_id), str(job_id))
        # BLE 一次任务要 15~20 秒（预检一次连接 + 打印一次连接），轮询等它完成
        job = {}
        for _ in range(30):
            time.sleep(2)
            st, body = c.req("GET", "/jobs", timeout=30)
            jobs = {j["id"]: j for j in body.get("jobs", [])}
            job = jobs.get(job_id, {})
            if job.get("status") in ("done", "error", "deferred"):
                break
        check("定时任务执行完成", job.get("status") == "done", f"status={job.get('status')} err={job.get('lastError')}")
        st, _ = c.req("DELETE", f"/jobs/{job_id}", timeout=30)
        check("DELETE /jobs/<id>", st in (200, 404), str(st))
    finally:
        srv.terminate()


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default="00:15:83:E4:7A:F2")
    ap.add_argument("--no-http", action="store_true")
    ap.add_argument("--cli-only", action="store_true")
    args = ap.parse_args()

    print(f"真机完整测试  目标 {args.address}", flush=True)
    if not phase_a(args.address):
        return report()
    phase_b(args.address)
    if stopped:
        return report()
    if not args.cli_only and not args.no_http:
        phase_c(args.address)
    return report()


def report() -> int:
    print("\n" + "=" * 60)
    if stopped:
        print(f"⏸  已按要求停下：{stopped}")
    if fails:
        print(f"失败 {len(fails)} 项: {fails}")
        return 1
    print(f"全部通过 ✅（{passes} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
