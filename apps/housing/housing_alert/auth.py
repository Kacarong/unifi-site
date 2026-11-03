"""폼 CSRF 토큰. 외부 의존성 없이 표준 라이브러리만 쓴다."""
from __future__ import annotations

import hashlib
import hmac


def csrf_token(secret: str, session: dict) -> str:
    return hmac.new(secret.encode(), f"csrf:{session.get('sid')}".encode(), hashlib.sha256).hexdigest()[:32]
