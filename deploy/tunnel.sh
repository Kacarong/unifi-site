#!/usr/bin/env bash
# unifi-site 공개 터널.
#
# 고정 도메인이 준비돼 있으면(= ~/.cloudflared/config.yml 이 있으면) 그걸 쓰고,
# 없으면 주소가 매번 바뀌는 quick tunnel 로 뜬다. 고정 도메인을 붙이려면
# deploy/named-tunnel.sh 를 한 번 실행한다.
set -euo pipefail

PORT="${UNIFI_PORT:-8090}"
CONF_DIR="${UNIFI_CONF_DIR:-$HOME/.config/unifi-site}"
CLOUDFLARED="${CLOUDFLARED:-$HOME/bin/cloudflared}"
CF_DIR="${CLOUDFLARED_HOME:-$HOME/.cloudflared}"
URL_FILE="$CONF_DIR/public-url"
LOG="$CONF_DIR/tunnel.log"

mkdir -p "$CONF_DIR"
: > "$LOG"

# ── 고정 도메인이 준비된 경우 ─────────────────────────────────────────
if [ -f "$CF_DIR/config.yml" ] && [ -f "$CF_DIR/cert.pem" ]; then
  HOST=$(grep -oE '^[[:space:]]*-?[[:space:]]*hostname:[[:space:]]*\S+' "$CF_DIR/config.yml" \
         | head -1 | awk '{print $NF}')
  [ -n "${HOST:-}" ] && echo "https://$HOST" > "$URL_FILE"
  echo "공개 주소: https://${HOST:-(설정 확인 필요)}"
  exec "$CLOUDFLARED" --no-autoupdate --config "$CF_DIR/config.yml" tunnel run
fi

# ── 아직 없으면 임시 주소로 ───────────────────────────────────────────
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
