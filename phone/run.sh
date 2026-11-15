#!/usr/bin/env bash
# 手机端启动脚本（Termux proot Ubuntu 里用）
set -e
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
echo "启动 memobird phone server 端口 $PORT"
echo "在手机 Chrome 打开： http://127.0.0.1:$PORT"
exec python3 phone/serve.py --port "$PORT"
