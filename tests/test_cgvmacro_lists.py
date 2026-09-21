"""영화·극장 목록 캐시 테스트 (네트워크 없이 CGV 응답을 흉내낸다).

    python3 tests/test_cgvmacro_lists.py

목록은 계속 바뀌므로 화면에서 자주 새로 부른다. 그때마다 CGV 를 두드리면
안 되고(캐시), 그렇다고 영영 안 바뀌어도 안 되며(만료), 갱신에 실패했을 때
목록이 통째로 사라져서도 안 된다(이전 값 유지). 이 세 가지를 고정한다.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apps.cgvmacro.core import cgv_api  # noqa: E402

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: got {got!r}, want {want!r}")
        FAILURES.append(label)


class FakeCgv:
    """_get 을 대신한다. 호출 횟수를 세고, 원하면 실패시킨다."""

    def __init__(self) -> None:
        self.calls = 0
        self.fail = False
        self.movies = [{"movNo": "1", "movNm": "오디세이"}]

    def __call__(self, path, **params):
        self.calls += 1
        if self.fail:
            raise cgv_api.CgvApiError("일시적 오류")
        return list(self.movies)


def run() -> None:
    fake = FakeCgv()
    cgv_api._get = fake              # type: ignore[assignment]
    cgv_api._list_cache.clear()

    print("1) 처음엔 CGV 를 부른다")
    check("목록", cgv_api.list_movies(), [("1", "오디세이")])
    check("호출 1회", fake.calls, 1)

    print("2) 곧바로 다시 불러도 CGV 를 또 부르지 않는다")
    for _ in range(5):
        cgv_api.list_movies()
    check("호출 그대로 1회", fake.calls, 1)

    print("3) 보관 기간이 지나면 새로 받는다 (새 영화가 편성된 상황)")
    fake.movies.append({"movNo": "2", "movNm": "새로 개봉한 영화"})
    stamp, value = cgv_api._list_cache["movies"]
    cgv_api._list_cache["movies"] = (stamp - cgv_api.MOVIES_TTL - 1, value)  # 시간을 앞당긴다
    check("새 영화 포함", cgv_api.list_movies(), [("1", "오디세이"), ("2", "새로 개봉한 영화")])
    check("호출 2회", fake.calls, 2)

    print("4) 갱신에 실패하면 이전 목록을 유지한다")
    fake.fail = True
    stamp, value = cgv_api._list_cache["movies"]
    cgv_api._list_cache["movies"] = (stamp - cgv_api.MOVIES_TTL - 1, value)
    check("이전 목록 그대로", cgv_api.list_movies(), [("1", "오디세이"), ("2", "새로 개봉한 영화")])

    print("5) 가진 것도 없는데 실패하면 오류를 숨기지 않는다")
    cgv_api._list_cache.clear()
    try:
        cgv_api.list_movies()
        check("오류 발생", False, True)
    except cgv_api.CgvApiError:
        check("오류 발생", True, True)


if __name__ == "__main__":
    run()
    if FAILURES:
        print(f"\n실패 {len(FAILURES)}건: {', '.join(FAILURES)}")
        raise SystemExit(1)
    print("\n전부 통과")
