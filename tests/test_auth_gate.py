"""공개 배포용 비밀번호 게이트 테스트.

    python3 tests/test_auth_gate.py

여기가 틀리면 공개 주소에 그대로 노출된다. '비밀번호 없으면 API도 못 부른다',
'맞으면 들어간다', '쿠키 위조는 막힌다', '에이전트 경로는 토큰으로만 열린다'
네 가지를 고정한다.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="unifi-auth-test-")
os.environ["UNIFI_DATA_DIR"] = _TMP
os.environ["UNIFI_PASSWORD"] = "test-secret-pw"

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: got {got!r}, want {want!r}")
        FAILURES.append(label)


def run() -> None:
    client = TestClient(app)

    print("1) 로그인 전에는 막힌다")
    check("포털은 로그인 화면", client.get("/").status_code, 401)
    check("앱 API 401", client.get("/api/cgvmacro/monitor/status").status_code, 401)
    check("앱 목록 401", client.get("/api/_apps").status_code, 401)

    print("2) 열어둬야 하는 경로")
    check("헬스체크는 통과", client.get("/api/_health").status_code, 200)
    check("로그인 화면 스타일 통과", client.get("/style.css").status_code, 200)
    check("디자인 시스템 통과", client.get("/ui.css").status_code, 200)
    # 홈 화면 추가(PWA)와 브라우저 기본 아이콘 요청은 로그인 전에도 와야 한다
    check("매니페스트 통과", client.get("/manifest.webmanifest").status_code, 200)
    check("favicon 통과", client.get("/favicon.ico").status_code, 200)

    print("3) 틀린 비밀번호는 거부")
    check("401", client.post("/api/_login", json={"password": "nope"}).status_code, 401)
    check("쿠키 없음", "unifi_auth" in client.cookies, False)

    print("4) 맞는 비밀번호로 들어간다")
    check("200", client.post("/api/_login", json={"password": "test-secret-pw"}).status_code, 200)
    check("포털 열림", client.get("/").status_code, 200)
    check("앱 API 열림", client.get("/api/_apps").status_code, 200)

    print("5) 쿠키 위조는 통하지 않는다")
    forged = TestClient(app, cookies={"unifi_auth": "99999999999.deadbeef"})
    check("위조 쿠키 401", forged.get("/api/_apps").status_code, 401)
    expired = TestClient(app, cookies={"unifi_auth": "1.0"})
    check("만료 쿠키 401", expired.get("/api/_apps").status_code, 401)

    print("6) 에이전트 경로는 게이트를 지나지만 토큰이 필수")
    anon = TestClient(app)
    res = anon.post("/api/cgvmacro/agent/claim")
    check("토큰 미설정이면 503", res.status_code, 503)

    from apps.cgvmacro import store

    store.update_settings({"agent_token": "agent-tok"})
    check("토큰 틀리면 401", anon.post("/api/cgvmacro/agent/claim").status_code, 401)
    ok = anon.post("/api/cgvmacro/agent/claim", headers={"X-Agent-Token": "agent-tok"})
    check("토큰 맞으면 200", ok.status_code, 200)


if __name__ == "__main__":
    try:
        run()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)

    if FAILURES:
        print(f"\n실패 {len(FAILURES)}건: {', '.join(FAILURES)}")
        raise SystemExit(1)
    print("\n전부 통과")
