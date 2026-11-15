"""
mitm_capture.py — 抓「有道打印机 / 咕咕机」App 的私有接口（mitmproxy 插件）

这个 App（cn.memobird.XGWangYi v3.2.9）被 360 加固，dex 全加密，静态拿不到接口。
想拿到它真正用的域名 / 路径 / 参数 / ak / userid，就在手机上挂 mitmproxy 抓一遍。

用法：
    pip install mitmproxy
    mitmdump -s tools/mitm_capture.py --set memobird_out=capture.jsonl
    # 手机 WiFi 代理指向电脑 8080，浏览器访问 mitm.it 装证书；
    # 若 App 有证书固定（pinning），需要 frida 去 hook 或改用旧版本 APK

产出：
    capture.jsonl  每条一行：时间 / 方法 / URL / 请求头 / 请求体 / 响应体
    同时把命中的 host 汇总打印，方便直接找 API 基址。
"""
from __future__ import annotations

import json
import os
import time

from mitmproxy import http

OUT = os.environ.get("MEMOBIRD_CAPTURE_OUT", "capture.jsonl")

# 关心这些关键字（域名/路径/内容里出现即记录）
HINTS = (
    "memobird", "gugu", "XGWangYi", "youdao", "printpaper", "printPaper",
    "setuserbind", "getprintstatus", "xkw", "/sys/printer", "printer",
)

# 这些头体积大又没信息
DROP_HEADERS = {"accept-encoding", "user-agent", "connection", "content-length", "host"}


def _interesting(flow: http.HTTPFlow) -> bool:
    blob = (flow.request.pretty_url + " " + flow.request.get_text(strict=False)[:4000]).lower()
    return any(h.lower() in blob for h in HINTS)


def _record(flow: http.HTTPFlow) -> dict:
    req = flow.request
    resp = flow.response
    body = req.get_text(strict=False) or ""
    try:
        body_json = json.loads(body)
    except Exception:
        body_json = None
    resp_text = resp.get_text(strict=False) if resp is not None else ""
    return {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": req.method,
        "url": req.pretty_url,
        "req_headers": {k: v for k, v in req.headers.items() if k.lower() not in DROP_HEADERS},
        "req_body": body_json if body_json is not None else body[:8000],
        "status": resp.status_code if resp is not None else None,
        "resp_body": (resp_text or "")[:8000],
    }


def response(flow: http.HTTPFlow) -> None:
    if not _interesting(flow):
        return
    rec = _record(flow)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[capture] {rec['method']} {rec['url']}  -> {rec['status']}")
