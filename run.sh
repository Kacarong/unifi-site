#!/usr/bin/env bash
# unifi-site 실행 (리눅스/맥)
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "가상환경 생성 중..."
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

HOST="${UNIFI_HOST:-0.0.0.0}"
PORT="${UNIFI_PORT:-8000}"
echo "http://${HOST}:${PORT} 에서 실행합니다."
exec .venv/bin/python -m uvicorn server.main:app --host "$HOST" --port "$PORT" "$@"
