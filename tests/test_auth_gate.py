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
    # 로그인 화면도 같은 글꼴을 쓰므로 글꼴은 열려 있어야 한다
    check("글꼴 CSS 통과", client.get("/fonts.css").status_code, 200)
    check("글꼴 파일 통과", client.get("/fonts/PretendardVariable.subset.0.woff2").status_code, 200)

    print("3) 틀린 비밀번호는 거부")
    check("401", client.post("/api/_login", json={"password": "nope"}).status_code, 401)
    check("쿠키 없음", "unifi_auth" in client.cookies, False)

    print("4) 맞는 비밀번호로 들어간다")
    check("200", client.post("/api/_login", json={"password": "test-secret-pw"}).status_code, 200)
    check("포털 열림", client.get("/").status_code, 200)
    check("앱 API 열림", client.get("/api/_apps").status_code, 200)

    print("4-0) 로그인 상태는 쓰는 동안 저절로 연장된다")
    import time as _time

    from server import auth as _auth

    # 갓 받은 쿠키는 굳이 다시 주지 않는다. 매 응답에 쿠키를 붙일 이유가 없다.
    check("새 쿠키는 재발급 안 함",
          any(k.lower() == "set-cookie" for k in client.get("/").headers), False)
    # 절반 넘게 지난 쿠키는 조용히 새로 준다 — 30일마다 다시 로그인하지 않게.
    near = int(_time.time()) + 5 * 86400
    client.cookies.set("unifi_auth", f"{near}.{_auth._sign(near)}")
    r = client.get("/")
    check("얼마 안 남은 쿠키도 통과", r.status_code, 200)
    check("연장 시 새 쿠키를 내려준다",
          any(k.lower() == "set-cookie" for k in r.headers), True)
    # 새로 내려준 쿠키를 응답 헤더에서 직접 꺼내 본다.
    issued = r.headers["set-cookie"].split("unifi_auth=", 1)[1].split(";", 1)[0]
    check("연장된 기한이 더 길다", _auth.expires_in(issued) > 20 * 86400, True)
    # 위조한 쿠키는 연장은커녕 통과도 못 한다.
    client.cookies.clear()
    client.cookies.set("unifi_auth", f"{near}.deadbeef")
    check("위조 쿠키는 막힌다", client.get("/").status_code, 401)
    client.cookies.clear()
    check("다시 로그인",
          client.post("/api/_login", json={"password": "test-secret-pw"}).status_code, 200)

    print("4-1) 캐시 규칙 — 고친 화면이 옛 파일에 가려지면 안 된다")
    # 헤더가 없으면 브라우저가 서버에 묻지도 않고 옛 파일을 쓴다(실제로 겪음).
    for path in ("/", "/style.css", "/ui.css", "/app.js"):
        check(f"{path} 는 매번 확인", client.get(path).headers.get("cache-control"), "no-cache")
    # 내용이 바뀌면 이름이 바뀌는 것들만 영구 캐시
    check(
        "글꼴은 영구 캐시",
        client.get("/fonts/PretendardVariable.subset.0.woff2").headers.get("cache-control"),
        "public, max-age=31536000, immutable",
    )

    print("4-2) PC 전용 앱은 휴대폰에서 막힌다")
    PHONE = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"}
    PC = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}

    def cgv(headers):
        apps = client.get("/api/_apps", headers=headers).json()
        return next(a for a in apps if a["id"] == "cgvmacro")

    check("휴대폰에선 PC 전용 표시", cgv(PHONE)["status"], "desktop_only")
    check("휴대폰에선 열 주소 없음", cgv(PHONE)["url"], None)
    check("PC 에선 그대로 사용 가능", cgv(PC)["status"], "ready")
    # 주소를 직접 열어도 막혀야 한다
    phone_page = client.get("/apps/cgvmacro/", headers=PHONE)
    check("휴대폰 직접 접속은 안내 화면", "PC에서만" in phone_page.text, True)
    check("PC 직접 접속은 정상", client.get("/apps/cgvmacro/", headers=PC).status_code, 200)
    check("PC 화면엔 안내문 없음", "PC에서만" in client.get("/apps/cgvmacro/", headers=PC).text, False)
    # PC 전용이 아닌 앱은 휴대폰에서도 그대로
    apps = client.get("/api/_apps", headers=PHONE).json()
    check("다른 앱은 영향 없음", next(a for a in apps if a["id"] == "geoglobe")["status"], "ready")

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
