#!/usr/bin/env bash
# 고정 도메인 붙이기. 한 번만 실행하면 된다.
#
#   deploy/named-tunnel.sh unifi.kacarong.kr
#
# 먼저 끝나 있어야 하는 것 (둘 다 사람이 해야 한다):
#   1. Cloudflare 계정에 그 도메인이 zone 으로 등록돼 있고 상태가 Active 일 것
#      — 등록하면 Cloudflare 가 네임서버 두 개를 알려주고, 도메인 산 곳에서
#        네임서버를 그것으로 바꿔야 Active 가 된다.
#   2. `~/bin/cloudflared tunnel login` 으로 로그인해 cert.pem 이 있을 것
#
# 끝나면 systemd 유닛은 그대로 두고 unifi-tunnel 만 재시작하면 된다.
# tunnel.sh 가 config.yml 을 보고 알아서 고정 도메인으로 뜬다.
set -euo pipefail

HOST="${1:-}"
[ -n "$HOST" ] || { echo "사용법: $0 <호스트명>   예: $0 unifi.kacarong.kr" >&2; exit 2; }

PORT="${UNIFI_PORT:-8090}"
TUNNEL="${TUNNEL_NAME:-unifi-site}"
CLOUDFLARED="${CLOUDFLARED:-$HOME/bin/cloudflared}"
CF_DIR="${CLOUDFLARED_HOME:-$HOME/.cloudflared}"

[ -x "$CLOUDFLARED" ] || { echo "cloudflared 가 없습니다: $CLOUDFLARED" >&2; exit 1; }
if [ ! -f "$CF_DIR/cert.pem" ]; then
  echo "Cloudflare 로그인이 먼저입니다:" >&2
  echo "    $CLOUDFLARED tunnel login" >&2
  echo "실행하면 주소가 하나 나옵니다. 브라우저에서 열어 도메인을 고르면 됩니다." >&2
  exit 1
fi

# 같은 이름의 터널이 이미 있으면 다시 만들지 않는다.
if ! "$CLOUDFLARED" tunnel list | awk '{print $2}' | grep -qx "$TUNNEL"; then
  echo "[1/3] 터널 '$TUNNEL' 만드는 중…"
  "$CLOUDFLARED" tunnel create "$TUNNEL"
else
  echo "[1/3] 터널 '$TUNNEL' 이미 있음 — 그대로 씁니다."
fi

ID=$("$CLOUDFLARED" tunnel list | awk -v n="$TUNNEL" '$2==n {print $1}' | head -1)
[ -n "$ID" ] || { echo "터널 ID 를 찾지 못했습니다." >&2; exit 1; }

echo "[2/3] 설정 파일 쓰는 중… ($CF_DIR/config.yml)"
cat > "$CF_DIR/config.yml" <<YAML
# deploy/named-tunnel.sh 가 만든 파일. 직접 고쳐도 된다.
tunnel: $ID
credentials-file: $CF_DIR/$ID.json

ingress:
  - hostname: $HOST
    service: http://127.0.0.1:$PORT
  - service: http_status:404
YAML

# -f 를 주는 이유: 도메인을 Cloudflare 로 옮기면 원래 쓰던 A/CNAME 레코드가
# 그대로 따라온다. 그게 남아 있으면 "이미 있다"며 실패한다. 어차피 이 이름은
# 터널이 가져갈 것이므로 덮어쓴다.
echo "[3/3] DNS 레코드 거는 중… ($HOST → 터널)"
"$CLOUDFLARED" tunnel route dns --overwrite-dns "$TUNNEL" "$HOST"

echo
echo "끝났습니다. 아래로 적용하세요:"
echo "    systemctl --user restart unifi-tunnel.service"
echo "그 뒤 https://$HOST 로 접속됩니다."
