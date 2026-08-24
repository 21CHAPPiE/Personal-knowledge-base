#!/usr/bin/env sh
# 一键启动前后端（开发模式）。Ctrl+C 同时结束两个进程。
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

trap 'kill 0' INT TERM

(cd "$ROOT/backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
echo "backend: http://127.0.0.1:8000"

(cd "$ROOT/frontend" && npm run dev) &
echo "frontend: http://127.0.0.1:5173"

wait
