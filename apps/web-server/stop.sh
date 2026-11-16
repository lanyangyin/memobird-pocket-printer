#!/usr/bin/env bash
# 停止后台服务
cd "$(dirname "$0")/.." || exit 1

if [ -f server.pid ]; then
  PID="$(cat server.pid)"
  if kill "$PID" 2>/dev/null; then
    echo "已停止 pid=$PID"
  else
    echo "pid=$PID 已不在运行"
  fi
  rm -f server.pid
  exit 0
fi

if pkill -f "phone/serve.py"; then
  echo "已停止（按进程名匹配）"
else
  echo "没有在运行的服务"
fi
