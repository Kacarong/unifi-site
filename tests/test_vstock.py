"""가상 주식 바로가기 테스트.

    python3 tests/test_vstock.py

사이트는 virtual-stock.kro.kr 에서 돌고, 여기는 그쪽으로 넘겨 주기만 한다.
'포털에 카드가 뜬다', '누르면 그 주소로 간다', '하위 경로·쿼리가 그대로 붙는다',
'로그인 전에는 넘겨 주지 않는다' 를 고정한다.
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ["UNIFI_DATA_DIR"] = tempfile.mkdtemp(prefix="unifi-vstock-test-")
os.environ["UNIFI_PASSWORD"] = "test-secret-pw"
os.environ.pop("VSTOCK_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402

FAILURES: list[str] = []
SITE = "http://virtual-stock.kro.kr"


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: got {got!r}, want {want!r}")
        FAILURES.append(label)


def run() -> None:
    client = TestClient(app, follow_redirects=False)

    print("1) 로그인 전에는 넘겨 주지 않는다")
    r = client.get("/apps/vstock/")
    check("로그인 화면", r.status_code, 401)
    check("이동 헤더 없음", r.headers.get("location"), None)

    client.post("/api/_login", json={"password": "test-secret-pw"})

    print("2) 포털 카드")
    card = next((a for a in client.get("/api/_apps").json() if a["id"] == "vstock"), None)
    check("목록에 있다", card is not None, True)
    check("바로 열 수 있다", card and card["status"], "ready")
    check("카드 주소", card and card["url"], "/apps/vstock/")

    print("3) 누르면 가상 주식 사이트로")
    for path, want in (
        ("/apps/vstock/", f"{SITE}/"),
        ("/apps/vstock", f"{SITE}/"),
        ("/apps/vstock/ranking", f"{SITE}/ranking"),
        ("/apps/vstock/stocks/005930?tab=chart", f"{SITE}/stocks/005930?tab=chart"),
    ):
        r = client.get(path)
        check(f"{path} 302", r.status_code, 302)
        check(f"{path} → {want}", r.headers.get("location"), want)


if __name__ == "__main__":
    run()
    if FAILURES:
        print(f"\n실패 {len(FAILURES)}건: {FAILURES}")
        sys.exit(1)
    print("\n모두 통과")
