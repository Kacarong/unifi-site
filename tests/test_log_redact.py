"""로그 비밀값 가리기 테스트.

    python3 tests/test_log_redact.py

공공데이터포털 인증키(serviceKey)가 httpx 요청 로그에 찍히지 않는지,
그러면서도 요청 로그 자체(주소·다른 파라미터·응답 코드)는 남는지를 고정한다.
실제 httpx 클라이언트가 남기는 로그를 그대로 받아서 본다.
"""
from __future__ import annotations

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import httpx  # noqa: E402

from server import log_redact  # noqa: E402

FAILURES: list[str] = []
KEY = "AbC123%2Bsecret%3D%3D"
WEBHOOK_TOKEN = "wh-tok_XYZ.987"


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        FAILURES.append(name)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def _httpx_log_lines(*requests: tuple[str, str, dict | None]) -> list[str]:
    cap = _Capture()
    logger = logging.getLogger("httpx")
    logger.addHandler(cap)
    logger.setLevel(logging.INFO)
    try:
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
        with httpx.Client(transport=transport) as client:
            for method, url, params in requests:
                client.request(method, url, params=params)
    finally:
        logger.removeHandler(cap)
    return cap.lines


def run() -> None:
    log_redact.install()
    log_redact.install()  # 두 번 불러도 필터는 하나
    check("필터 중복 없음", sum(isinstance(f, log_redact.RedactSecretsFilter)
                          for f in logging.getLogger("httpx").filters) == 1)

    lines = _httpx_log_lines(
        ("GET", "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1",
         {"serviceKey": KEY, "PG_SZ": 100, "PAGE": 2}),
        ("GET", "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail",
         {"page": 1, "serviceKey": KEY, "returnType": "JSON"}),
        ("POST", f"https://discord.com/api/webhooks/123456/{WEBHOOK_TOKEN}?wait=true", None),
    )
    text = "\n".join(lines)
    check("요청 3건 모두 로그에 남음", len(lines) == 3)
    check("serviceKey 값이 로그에 없음", "AbC123" not in text and "secret" not in text)
    check("웹훅 토큰이 로그에 없음", WEBHOOK_TOKEN not in text)
    check("LH API: 키만 가리고 나머지 파라미터 유지",
          "lhLeaseNoticeInfo1?serviceKey=***&PG_SZ=100&PAGE=2" in text)
    check("청약홈 API: 중간 위치의 키도 가림",
          "page=1&serviceKey=***&returnType=JSON" in text)
    check("웹훅: 경로 토큰만 가림", "/api/webhooks/123456/***?wait=true" in text)
    check("응답 코드는 그대로", text.count("200 OK") == 3)

    check("비밀값 없는 주소는 그대로",
          log_redact.redact("GET https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1026")
          == "GET https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1026")


if __name__ == "__main__":
    run()
    if FAILURES:
        print(f"\n실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("\n모두 통과")
