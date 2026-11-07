"""httpx 요청 로그에서 비밀값을 가린다.

httpx 는 INFO 로 `HTTP Request: GET <전체 URL> ...` 을 남기는데, 공공데이터포털
API 는 인증키를 `serviceKey=` 쿼리로 받으므로 키가 로그에 그대로 찍힌다.
로그 자체는 장애 추적에 쓰이니 끄지 않고, 비밀값 부분만 `***` 로 바꾼다.
"""
from __future__ import annotations

import logging
import re

# 쿼리 파라미터 이름이 비밀값을 뜻하면 값만 가린다(serviceKey, api_key, token …).
_SECRET_QUERY = re.compile(
    r"(?i)([?&](?:service_?key|api_?key|key|access_?token|token|secret|password)=)[^&\s\"']+"
)
# 디스코드 웹훅 URL 은 경로에 토큰이 들어 있다: /api/webhooks/<id>/<token>
_WEBHOOK_TOKEN = re.compile(r"(/api/webhooks/\d+/)[^/?\s\"']+")


def redact(text: str) -> str:
    text = _SECRET_QUERY.sub(r"\1***", text)
    return _WEBHOOK_TOKEN.sub(r"\1***", text)


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = redact(msg)
        if clean != msg:
            record.msg = clean
            record.args = None
        return True


def install() -> None:
    """httpx 로거에 필터를 한 번만 붙인다."""
    logger = logging.getLogger("httpx")
    if not any(isinstance(f, RedactSecretsFilter) for f in logger.filters):
        logger.addFilter(RedactSecretsFilter())
