#!/usr/bin/env bash
# 后台启动（写 pid 与日志，适合日常使用）
set -e
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
PIDFILE="server.pid"
LOG="server.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "已在运行：pid=$(cat "$PIDFILE")  端口 $PORT"
  echo "打开 http://127.0.0.1:$PORT"
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "找不到 python3，先 apt install python3 python3-pil" >&2
  exit 1
fi

nohup python3 phone/serve.py --port "$PORT" >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
sleep 1

if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "已启动：pid=$(cat "$PIDFILE")  日志：$LOG"
  echo "手机 Chrome 打开 http://127.0.0.1:$PORT"
else
  echo "启动失败，最后 20 行日志：" >&2
  tail -n 20 "$LOG" >&2
  rm -f "$PIDFILE"
  exit 1
fi
