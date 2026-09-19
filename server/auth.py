"""사이트 전체 비밀번호 게이트 — 공개 배포용.

`UNIFI_PASSWORD` 가 설정돼 있을 때만 켜진다. 비어 있으면(로컬 실행 기본값)
아무 것도 하지 않으므로 개발 흐름은 그대로다.

쿠키는 서버가 보관하는 랜덤 비밀키로 서명한다. 비밀번호 자체는 쿠키에
들어가지 않고, 비밀키가 바뀌면 기존 세션은 모두 무효가 된다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from .paths import BASE

COOKIE_NAME = "unifi_auth"
SESSION_DAYS = 30

# 공개로 둬야 하는 경로 — 로그인 화면이 쓰는 자원, 상태 확인,
# 그리고 홈 화면 추가(PWA)에 필요한 매니페스트/아이콘. 비밀은 없다.
PUBLIC_PATHS = {
    "/api/_login",
    "/api/_health",
    "/ui.css",
    "/ui.js",
    "/style.css",
    "/manifest.webmanifest",
    "/icon.svg",
    "/icon-180.png",
    "/icon-192.png",
    "/icon-512.png",
}
# 로컬 PC 에이전트는 쿠키가 없다. 대신 X-Agent-Token 으로 인증한다
# (공개 모드에서는 해당 토큰 설정이 필수 — apps/cgvmacro/api.py 참고).
PUBLIC_PREFIXES = ("/api/cgvmacro/agent/",)

_FAIL_WINDOW = 300  # 초
_MAX_FAILS = 5
_fails: dict[str, list[float]] = {}


def password() -> str:
    return os.environ.get("UNIFI_PASSWORD", "").strip()


def enabled() -> bool:
    return bool(password())


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def _secret() -> bytes:
    """세션 서명용 비밀키. 없으면 만들어 두고 재사용한다."""
    os.makedirs(BASE, exist_ok=True)
    path = os.path.join(BASE, "session_secret")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip().encode()


def _sign(expires_at: int) -> str:
    msg = f"{expires_at}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def issue() -> str:
    expires_at = int(time.time()) + SESSION_DAYS * 86400
    return f"{expires_at}.{_sign(expires_at)}"


def valid(cookie: str | None) -> bool:
    if not cookie or "." not in cookie:
        return False
    raw_exp, _, sig = cookie.partition(".")
    try:
        expires_at = int(raw_exp)
    except ValueError:
        return False
    if expires_at < time.time():
        return False
    return hmac.compare_digest(sig, _sign(expires_at))


def check_password(candidate: str, client: str) -> bool:
    """비밀번호 확인. 같은 IP에서 연속 실패하면 잠시 막는다."""
    now = time.time()
    if len(_fails) > 1000:  # 공개 주소라 IP 가 무한정 쌓이지 않게 정리한다
        for ip, times in list(_fails.items()):
            if all(now - t >= _FAIL_WINDOW for t in times):
                del _fails[ip]
    recent = [t for t in _fails.get(client, []) if now - t < _FAIL_WINDOW]
    if len(recent) >= _MAX_FAILS:
        _fails[client] = recent
        raise TooManyAttempts(int(_FAIL_WINDOW - (now - recent[0])) + 1)

    if hmac.compare_digest(candidate or "", password()):
        _fails.pop(client, None)
        return True

    recent.append(now)
    _fails[client] = recent
    return False


class TooManyAttempts(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"too many attempts, retry after {retry_after}s")
        self.retry_after = retry_after
