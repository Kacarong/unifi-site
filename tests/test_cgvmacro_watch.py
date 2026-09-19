"""cgv-macro 감시 판정 로직 테스트 — 네트워크 없이 회차 응답을 흉내낸다.

    python tests/test_cgvmacro_watch.py

여기가 틀리면 알림이 안 오거나(놓침) 등록하자마자 쏟아진다(도배). 그래서
'첫 폴링은 기준선', '매진→잔여만 취소표', '같은 회차 중복 선점 금지' 세 가지를
고정해 둔다.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# store 가 import 시점에 경로를 잡으므로 먼저 격리된 데이터 폴더를 지정한다.
_TMP = tempfile.mkdtemp(prefix="unifi-test-")
os.environ["UNIFI_DATA_DIR"] = _TMP

from apps.cgvmacro import store, watch  # noqa: E402
from apps.cgvmacro.core.cgv_api import Showtime  # noqa: E402

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: got {got!r}, want {want!r}")
        FAILURES.append(label)


def showtime(time: str, remaining: int, total: int = 100) -> Showtime:
    return Showtime(
        time=time,
        screen="1관",
        fmt="2D",
        remaining=remaining,
        total=total,
        soldout=(remaining == 0),
        schedule_id="1",
        scns_no="001",
        raw={},
    )


class FakeApi:
    """watch 모듈이 쓰는 cgv_api 를 대체한다."""

    def __init__(self) -> None:
        self.showtimes: list[Showtime] = []

    def resolve_movie(self, movie, movie_code=""):
        return ("MOV", movie or "영화")

    def resolve_theater(self, theater, theater_code=""):
        return ("SITE", theater or "극장", "지역")

    def fetch_showtimes(self, mov_no, site_no, date):
        return list(self.showtimes)

    def stage_event_label(self, raw):
        return ""


def run() -> None:
    fake = FakeApi()
    watch.cgv_api = fake  # type: ignore[assignment]

    watcher = watch.Watcher()
    target = store.add_target(
        {"name": "T", "movie": "영화", "theater": "극장", "date": "2026-09-25", "auto_grab": True}
    )

    print("1) 첫 폴링은 기준선만 — 이미 열려 있던 회차로 알리지 않는다")
    fake.showtimes = [showtime("10:00", 50), showtime("13:00", 0)]
    watcher._poll_target(store.get_target(target["id"]), None)
    check("이벤트 없음", len(store.list_events()), 0)
    check("선점 작업 없음", len(store.list_jobs()), 0)
    check("기준선 기록됨", store.get_target(target["id"])["baselined"], True)

    print("2) 변화가 없으면 조용하다")
    watcher._poll_target(store.get_target(target["id"]), None)
    check("이벤트 없음", len(store.list_events()), 0)

    print("3) 매진 → 잔여석 = 취소표 + 자동 선점 작업")
    fake.showtimes = [showtime("10:00", 50), showtime("13:00", 3)]
    watcher._poll_target(store.get_target(target["id"]), None)
    events = store.list_events()
    check("이벤트 1건", len(events), 1)
    check("종류는 취소표", events[0]["kind"], "cancel")
    check("13시 회차", events[0]["time"], "13:00")
    check("선점 작업 1건", len(store.list_jobs()), 1)

    print("4) 같은 회차가 계속 잔여여도 작업을 또 만들지 않는다")
    watcher._poll_target(store.get_target(target["id"]), None)
    check("선점 작업 그대로 1건", len(store.list_jobs()), 1)
    check("이벤트 그대로 1건", len(store.list_events()), 1)

    print("5) 새 회차가 열리면 '상영 오픈' 한 건만 (잔여석 알림과 겹치지 않는다)")
    fake.showtimes.append(showtime("16:00", 80))
    watcher._poll_target(store.get_target(target["id"]), None)
    kinds = [e["kind"] for e in store.list_events() if e["time"] == "16:00"]
    check("오픈 알림 1건", kinds, ["open"])
    check("신규 회차도 자동 선점", len(store.list_jobs()), 2)

    print("6) 대상 조건을 바꾸면 기준선을 다시 잡는다")
    store.update_target(target["id"], {"date": "2026-09-26"})
    updated = store.get_target(target["id"])
    check("baselined 초기화", updated["baselined"], False)
    check("seen 초기화", updated["seen"], {})


if __name__ == "__main__":
    try:
        run()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)

    if FAILURES:
        print(f"\n실패 {len(FAILURES)}건: {', '.join(FAILURES)}")
        raise SystemExit(1)
    print("\n전부 통과")
