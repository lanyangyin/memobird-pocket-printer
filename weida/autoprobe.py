"""WeiDa/Dothantech 标签机 —— 自驱探针（自己跑、自己记录、自己改）。

设计要点
--------
1. **安全白名单**：只发厂商 App 初始化时自己就会发的探测命令，绝不发未知/破坏性命令。
2. **自己观察**：每次发送后记录"有没有回包 / 回包字节 / 耗时"，写进 knowledge.json。
3. **自己改自己**：
   * 把学到的结论写进 knowledge.json，下次启动先加载（越跑越准）
   * 根据"回包率"自动调整节奏参数（分片大小 / 片间延时），存到 state.json
   * 连续两轮无新发现就切换策略（换探测顺序 / 加大等待）
4. **可模拟**：`--sim` 用假的传输层跑完整循环，没设备也能验证逻辑。

用法
----
    python weida/autoprobe.py --sim --rounds 3          # 模拟跑，验证自驱循环
    python weida/autoprobe.py --addr 00:15:83:E4:7A:F2  # 真机
    python weida/autoprobe.py --addr ... --print        # 额外打一张 8 行的测试图
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import weida_protocol as W  # noqa: E402

KNOWLEDGE = os.path.join(HERE, "knowledge.json")
STATE = os.path.join(HERE, "state.json")
REPORT = os.path.join(HERE, "autoprobe_report.md")

# 厂商 App 初始化时自己会发的探测命令（安全白名单，来自 printer/a.java:4230-4260）
SAFE_PROBES = [
    0x7C, 0x79, 0x7A, 0x75, 0x7D, 0x71, 0x72, 0x52, 0x57, 0x59,
    0x44, 0x9F, 0x83, 0x0A, 0x29, 0x70, 0x84, 0x43, 0x42, 0x88,
    0x45, 0x47, 0x48, 0x49, 0x4D, 0x73, 0x7F,
]

DEFAULT_STATE = {
    "chunk": 20,          # BLE 分片
    "settle_ms": 8,       # 片间延时
    "reply_wait_ms": 400,  # 等回包
    "rounds_done": 0,
    "probe_order": "fixed",
}


# --------------------------------------------------------------------------- #
# 传输层：真机（BLE）与模拟器
# --------------------------------------------------------------------------- #
class SimLink:
    """模拟设备：对一部分命令回包，用来验证自驱逻辑。"""

    def __init__(self):
        self.answers = {0x79, 0x7A, 0x70, 0x44, 0x9F}   # 假装这 5 条有应答
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def transact(self, frame: bytes, wait: float = 0.4) -> list[bytes]:
        self.sent.append(frame)
        await asyncio.sleep(0.01)
        if len(frame) >= 2 and frame[0] == 0xAA:
            cmd = frame[1]
            if cmd in self.answers:
                # 造一个回包：BB cmd 02 <随机 2 字节> crc
                payload = bytes([0x00, random.randint(1, 9)])
                return [bytes([0xBB, cmd, len(payload)]) + payload
                        + bytes([W.checksum(cmd, payload)])]
        return []


class BleLink:
    """真机：FF00/FF02 写、FF03 收信用额度（P1 实测路径）。"""

    FF01 = "0000ff01-0000-1000-8000-00805f9b34fb"
    FF02 = "0000ff02-0000-1000-8000-00805f9b34fb"
    FF03 = "0000ff03-0000-1000-8000-00805f9b34fb"

    def __init__(self, addr: str, chunk: int = 20, settle_ms: int = 8):
        self.addr = addr
        self.chunk = chunk
        self.settle = settle_ms / 1000.0
        self.client = None
        self.rx: list[bytes] = []
        self.credits = 0
        self._cond = None
        self._loop = None

    def _on_ff03(self, _s, data: bytearray):
        raw = bytes(data)
        self.rx.append(raw)
        if len(raw) >= 2 and raw[0] == 0x01 and self._cond:
            self._loop.create_task(self._grant(raw[1]))

    def _on_ff01(self, _s, data: bytearray):
        self.rx.append(bytes(data))

    async def _grant(self, n: int):
        async with self._cond:
            self.credits += n
            self._cond.notify_all()

    async def __aenter__(self):
        from bleak import BleakClient

        self._loop = asyncio.get_running_loop()
        self._cond = asyncio.Condition()
        self.client = BleakClient(self.addr, timeout=25)
        for attempt in range(4):
            try:
                await self.client.connect()
                break
            except Exception:
                if attempt == 3:
                    raise
                await asyncio.sleep(1.5)
        try:
            await self.client.start_notify(self.FF03, self._on_ff03)
        except Exception:                              # noqa: BLE001
            pass
        try:
            await self.client.start_notify(self.FF01, self._on_ff01)
        except Exception:                              # noqa: BLE001
            pass
        await asyncio.sleep(1.2)
        self.rx.clear()
        return self

    async def __aexit__(self, *exc):
        try:
            await self.client.disconnect()
        except Exception:
            pass
        return False

    async def transact(self, frame: bytes, wait: float = 0.4) -> list[bytes]:
        """按额度发送，返回这段时间收到的 FF03/FF01 消息。"""
        mark = len(self.rx)
        for i in range(0, len(frame), self.chunk):
            piece = frame[i:i + self.chunk]
            deadline = time.time() + 6.0
            async with self._cond:
                while self.credits <= 0 and time.time() < deadline:
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=0.3)
                    except asyncio.TimeoutError:
                        pass
                if self.credits > 0:
                    self.credits -= 1
            try:
                await self.client.write_gatt_char(self.FF02, piece, response=False)
            except Exception:                          # noqa: BLE001
                await self.client.write_gatt_char(self.FF02, piece, response=True)
            if self.settle:
                await asyncio.sleep(self.settle)
        await asyncio.sleep(wait)
        return self.rx[mark:]


# --------------------------------------------------------------------------- #
# 自驱探针
# --------------------------------------------------------------------------- #
class AutoProbe:
    def __init__(self, sim: bool, addr: str):
        self.sim = sim
        self.addr = addr
        self.state = self._load(STATE, DEFAULT_STATE)
        self.knowledge = self._load(KNOWLEDGE, {"probes": {}, "notes": []})
        self.round = 0

    # ---------------- 持久化 ----------------
    @staticmethod
    def _load(path: str, default: dict) -> dict:
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    merged = dict(default)
                    merged.update(data)
                    return merged
            except Exception:
                pass
        return dict(default)

    @staticmethod
    def _save(path: str, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ---------------- 连接 ----------------
    async def _open(self):
        if self.sim:
            return SimLink()
        return BleLink(self.addr, self.state["chunk"], self.state["settle_ms"])

    # ---------------- 一轮探测 ----------------
    async def run_round(self) -> dict:
        self.round += 1
        order = list(SAFE_PROBES)
        if self.state.get("probe_order") == "shuffled":
            random.shuffle(order)

        stats = {"probes": 0, "replies": 0, "new": [], "errors": []}
        t0 = time.time()
        try:
            async with await self._open() as link:
                for cmd in order:
                    frame = W.frame(cmd)
                    stats["probes"] += 1
                    try:
                        replies = await link.transact(
                            frame, wait=self.state["reply_wait_ms"] / 1000.0)
                    except Exception as exc:            # noqa: BLE001
                        stats["errors"].append(f"0x{cmd:02X}: {type(exc).__name__}")
                        continue
                    # FF03 的 "01 nn" 是信用额度，不是命令回包 —— 要滤掉
                    real = [r for r in replies
                            if not (len(r) >= 2 and r[0] == 0x01)]
                    stats["credits"] = stats.get("credits", 0) + (
                        len(replies) - len(real))
                    replies = real
                    key = f"0x{cmd:02X}"
                    prev = self.knowledge["probes"].get(key) or {}
                    if replies:
                        stats["replies"] += 1
                        hexes = [r.hex(" ") for r in replies]
                        entry = {"reply": True, "last": hexes[-1],
                                 "count": prev.get("count", 0) + 1,
                                 "at": time.strftime("%Y-%m-%d %H:%M:%S")}
                        if not prev.get("reply"):
                            stats["new"].append(key)
                        self.knowledge["probes"][key] = entry
                    elif not prev:
                        self.knowledge["probes"][key] = {"reply": False, "count": 1}
        except Exception as exc:                        # noqa: BLE001
            stats["errors"].append(f"connect: {type(exc).__name__}: {exc}")

        stats["elapsed"] = round(time.time() - t0, 1)
        stats["rate"] = round(stats["replies"] / stats["probes"], 2) if stats["probes"] else 0
        self.state["rounds_done"] += 1
        self._adapt(stats)
        self._save(STATE, self.state)
        self._save(KNOWLEDGE, self.knowledge)
        self._write_report(stats)
        return stats

    # ---------------- 自己改自己 ----------------
    def _adapt(self, stats: dict) -> None:
        """根据这一轮的表现调整自己的参数/策略。"""
        changes = []

        # 一直没回包：多半是节奏太快或设备不在 → 放慢
        if stats["probes"] and stats["replies"] == 0:
            if self.state["settle_ms"] < 40:
                self.state["settle_ms"] = min(40, self.state["settle_ms"] * 2)
                changes.append(f"回包率 0 → settle {self.state['settle_ms']}ms")
            if self.state["chunk"] > 20:
                self.state["chunk"] = 20
                changes.append("分片回退到 20 字节")

        # 回包率很高：可以适当提速
        if stats["rate"] >= 0.8 and self.state["settle_ms"] > 2:
            self.state["settle_ms"] = max(2, self.state["settle_ms"] // 2)
            changes.append(f"回包率 {stats['rate']} → settle {self.state['settle_ms']}ms")

        # 有错误：加大等待
        if stats["errors"] and self.state["reply_wait_ms"] < 1500:
            self.state["reply_wait_ms"] = min(1500, self.state["reply_wait_ms"] + 200)
            changes.append(f"出现错误 → 等待 {self.state['reply_wait_ms']}ms")

        # 连续两轮没有新发现 → 换探测顺序
        self._no_new = getattr(self, "_no_new", 0) + (0 if stats["new"] else 1)
        if self._no_new >= 2 and self.state.get("probe_order") == "fixed":
            self.state["probe_order"] = "shuffled"
            changes.append("连续无新发现 → 探测顺序改为随机")

        if changes:
            self.knowledge.setdefault("notes", []).append(
                {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "round": self.round,
                 "changes": changes})
            print("  🔧 自我调整：" + "；".join(changes))

    def _write_report(self, stats: dict) -> None:
        known = self.knowledge["probes"]
        yes = sorted(k for k, v in known.items() if v.get("reply"))
        no = sorted(k for k, v in known.items() if not v.get("reply"))
        lines = [
            "# 自驱探针报告（自动生成）",
            "",
            f"更新：{time.strftime('%Y-%m-%d %H:%M:%S')}　轮次：{self.round}",
            "",
            f"本轮：探测 {stats['probes']}，命令回包 {stats['replies']}，"
            f"信用额度消息 {stats.get('credits', 0)}，"
            f"新发现 {len(stats['new'])}，耗时 {stats['elapsed']}s",
            "",
            f"## 有应答的命令（{len(yes)}）",
            "",
            "```",
            " ".join(yes) if yes else "(无)",
            "```",
            "",
            f"## 无应答（{len(no)}）",
            "",
            "```",
            " ".join(no) if no else "(无)",
            "```",
            "",
            "## 当前自适应参数",
            "",
            "```json",
            json.dumps({k: self.state[k] for k in
                        ("chunk", "settle_ms", "reply_wait_ms", "probe_order")},
                       ensure_ascii=False, indent=2),
            "```",
        ]
        if stats["errors"]:
            lines += ["", "## 本轮错误", ""] + [f"- {e}" for e in stats["errors"]]
        with open(REPORT, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # ---------------- 打印验证（可选） ----------------
    async def try_print(self) -> dict:
        """用文档里的 GS v 0 路径打一张 8 行的小图，看能不能过。"""
        W_, H_ = 384, 8
        raw = bytes([0xFF] * ((W_ + 7) // 8) * H_)
        stream = W.job_from_1bpp(raw, W_, H_, line_dots=24)
        t0 = time.time()
        try:
            async with await self._open() as link:
                replies = await link.transact(stream, wait=1.0)
            return {"ok": True, "bytes": len(stream),
                    "replies": [r.hex(" ")[:40] for r in replies],
                    "elapsed": round(time.time() - t0, 1)}
        except Exception as exc:                        # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
async def find_printer(match: str, timeout: float = 8.0) -> list[dict]:
    """找名字里包含 match 的 BLE 设备（默认找德佟 P1 一类）。"""
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    want = (match or "").lower()
    out = []
    for addr, (dev, adv) in found.items():
        name = (dev.name or adv.local_name or "")
        if not want or want in name.lower():
            out.append({"addr": addr, "name": name or "(无名)", "rssi": adv.rssi})
    return out


async def device_present(addr: str, timeout: float = 6.0) -> bool:
    """扫一下目标设备在不在广播。"""
    try:
        from bleak import BleakScanner

        found = await BleakScanner.discover(timeout=timeout)
        return any(d.address.upper() == addr.upper() for d in found)
    except Exception:                                  # noqa: BLE001
        return False


async def watch(probe: "AutoProbe", minutes: float, interval: float,
                rounds: int, auto_print: bool) -> int:
    """守候模式：设备一上线就跑一轮，跑完继续盯。"""
    deadline = time.time() + minutes * 60
    cycles = 0
    while time.time() < deadline:
        left = int(deadline - time.time())
        if not await device_present(probe.addr):
            print(f"  [{time.strftime('%H:%M:%S')}] 设备不在，{interval:.0f}s 后再看（剩 {left}s）",
                  flush=True)
            await asyncio.sleep(interval)
            continue

        print(f"  [{time.strftime('%H:%M:%S')}] 设备上线 → 开始探测", flush=True)
        for i in range(rounds):
            stats = await probe.run_round()
            print(f"    轮 {i + 1}: 探测 {stats['probes']} 回包 {stats['replies']} "
                  f"额度 {stats.get('credits', 0)} 新发现 {len(stats['new'])}", flush=True)
            if stats["errors"]:
                print("      错误: " + "; ".join(stats["errors"][:2]), flush=True)
        if auto_print:
            r = await probe.try_print()
            print("    打印验证: " + json.dumps(r, ensure_ascii=False), flush=True)
            probe.knowledge.setdefault("prints", []).append(
                {"at": time.strftime("%Y-%m-%d %H:%M:%S"), **r})
            AutoProbe._save(KNOWLEDGE, probe.knowledge)
        cycles += 1
        await asyncio.sleep(max(30.0, interval))

    print(f"  守候结束：完成 {cycles} 个周期", flush=True)
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser(description="WeiDa 标签机自驱探针")
    ap.add_argument("--sim", action="store_true", help="用模拟设备跑（无真机）")
    ap.add_argument("--addr", default="", help="设备地址；留空则按 --match 自动找")
    ap.add_argument("--match", default="P1",
                    help="设备名里包含这个字符串就认为是要找的打印机（默认 P1）")
    ap.add_argument("--list", dest="do_list", action="store_true",
                    help="只列设备，不探测")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--print", dest="do_print", action="store_true",
                    help="探完再打一张 8 行测试图")
    ap.add_argument("--watch", type=float, default=0,
                    help="守候模式：盯 N 分钟，设备一上线就跑")
    ap.add_argument("--interval", type=float, default=20,
                    help="守候模式的轮询间隔（秒）")
    ap.add_argument("--auto-print", action="store_true",
                    help="守候模式下每轮顺手打一张测试图")
    args = ap.parse_args()

    if args.do_list:
        cands = await find_printer(args.match, timeout=10.0)
        if not cands:
            print(f"  没找到名字含 {args.match!r} 的设备（蓝牙开了吗？）")
        for c in cands:
            print(f"    {c['addr']}  {c['name']}  rssi={c['rssi']}")
        return 0

    if not args.sim and not args.addr:
        cands = await find_printer(args.match, timeout=10.0)
        if not cands:
            print(f"  没找到名字含 {args.match!r} 的设备；"
                  f"用 --list 看看周围有什么，或用 --addr 指定地址")
            return 2
        args.addr = cands[0]["addr"]
        print(f"  自动选中：{args.addr}  {cands[0]['name']}")

    probe = AutoProbe(args.sim, args.addr)
    if args.watch > 0 and not args.sim:
        return await watch(probe, args.watch, args.interval, args.rounds, args.auto_print)
    print(f"  自驱探针启动（{'模拟' if args.sim else '真机'}）")
    print(f"  已加载知识：{len(probe.knowledge['probes'])} 条，"
          f"参数 chunk={probe.state['chunk']} settle={probe.state['settle_ms']}ms")

    for i in range(args.rounds):
        stats = await probe.run_round()
        print(f"  第 {i + 1} 轮：探测 {stats['probes']}，回包 {stats['replies']}，"
              f"新发现 {len(stats['new'])}{'（' + ','.join(stats['new']) + '）' if stats['new'] else ''}")
        if stats["errors"]:
            print("    错误：" + "; ".join(stats["errors"][:3]))
        if i + 1 < args.rounds:
            await asyncio.sleep(1.0)

    if args.do_print:
        r = await probe.try_print()
        print("  打印验证：", json.dumps(r, ensure_ascii=False))

    print(f"  结果：{REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
