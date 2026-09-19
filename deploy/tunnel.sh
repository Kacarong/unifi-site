#!/usr/bin/env bash
# unifi-site 공개 터널 (Cloudflare Quick Tunnel). 접속 주소를 파일로 남긴다.
#
# 주의: quick tunnel 의 주소는 재시작할 때마다 바뀐다. 고정 주소가 필요하면
# README 의 "고정 도메인" 절을 따라 named tunnel 또는 리버스 프록시로 바꾼다.
set -euo pipefail

PORT="${UNIFI_PORT:-8090}"
CONF_DIR="${UNIFI_CONF_DIR:-$HOME/.config/unifi-site}"
CLOUDFLARED="${CLOUDFLARED:-$HOME/bin/cloudflared}"
URL_FILE="$CONF_DIR/public-url"
LOG="$CONF_DIR/tunnel.log"

mkdir -p "$CONF_DIR"
: > "$LOG"

"$CLOUDFLARED" tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}" >>"$LOG" 2>&1 &
CF_PID=$!

# cloudflared 가 주소를 출력할 때까지 기다렸다가 기록한다.
for _ in $(seq 1 60); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
  [ -n "${URL:-}" ] && break
  sleep 1
done

if [ -n "${URL:-}" ]; then
  echo "$URL" > "$URL_FILE"
  echo "공개 주소: $URL"
else
  echo "터널 주소를 얻지 못했습니다. $LOG 확인" >&2
fi

wait "$CF_PID"
