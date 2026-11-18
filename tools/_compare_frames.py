"""对照实验：同一句文字，分别用「打印服务」和「网页」的编码链路生成帧，逐字节比对。

如果两边的帧完全相同，说明网页发出去的东西没问题，差异只可能出在浏览器侧的节奏/收尾；
如果不同，就能直接看出差在哪。
"""
import base64
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEXT = "SAME TEXT 123"


def post(path, payload):
    req = urllib.request.Request(
        "http://127.0.0.1:8766" + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def main():
    from memobird_printer import packet

    # 1) 服务端 /api/encode 给出的帧（网页实际发送的就是这些）
    out = post("/api/encode", {"kind": "text", "text": TEXT, "format": "gbk"})
    web_frames = out["frames"]
    meta = out["meta"]

    # 2) Python 侧直接构造
    job = packet.job_for_text(TEXT)
    py_frames = [base64.b64encode(f).decode() for f in job.frames]

    print(f"  服务端 /api/encode: {len(web_frames)} 帧  {meta}")
    print(f"  Python job_for_text: {len(py_frames)} 帧")
    same = web_frames == py_frames
    print("  逐帧一致:", same)

    if not same:
        for i in range(max(len(web_frames), len(py_frames))):
            a = web_frames[i] if i < len(web_frames) else "(少)"
            b = py_frames[i] if i < len(py_frames) else "(少)"
            if a != b:
                print(f"    帧 {i + 1} 不同：")
                print(f"      web: {a[:80]}")
                print(f"      py : {b[:80]}")

    # 3) 网页最后会额外发一帧收尾（0x01），Python 侧也一样
    from memobird_printer import device

    term = base64.b64encode(device.status_frame()).decode()
    print("  收尾帧（两边都应是 0x01）:", term)
    print("  网页源码用的收尾帧:", "STATUS_FRAME" if open(
        os.path.join(ROOT, "apps", "web-server", "app.js"), encoding="utf-8"
    ).read().count("MBBle.STATUS_FRAME") else "❌ 不是 STATUS_FRAME")


if __name__ == "__main__":
    main()
