"""장학금 알리미 테스트 — 네트워크 없이 파싱·조건 판정·알림 고르기를 확인한다.

    python tests/test_scholarship.py

알리미는 틀리면 조용히 망가진다. 알림이 안 오면(놓침) 마감을 넘기고,
쏟아지면(도배) 꺼 버리게 된다. 그래서 다음을 고정해 둔다.
  - 붙어서 오는 학년·학교·계열 값이 제대로 잘리는지
  - 지역 장학금은 내 지역일 때만, 지역 무관 장학금은 늘 보이는지
  - 첫 확인은 기준선만 잡는지, 같은 알림을 두 번 보내지 않는지
  - 며칠 건너뛰어도 마감 알림이 한 번만 가는지
  - 보내기 실패는 표시하지 않아 다음에 다시 보내는지
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="unifi-test-")
os.environ["UNIFI_DATA_DIR"] = _TMP

from apps.scholarship import logic, source, store, worker  # noqa: E402

FAILURES: list[str] = []
KST = worker.KST
TODAY = dt.date(2026, 11, 3)


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: got {got!r}, want {want!r}")
        FAILURES.append(label)


HEADER = (
    "번호,운영기관명,상품명,운영기관구분,상품구분,학자금유형구분,대학구분,학년구분,학과구분,"
    "성적기준 상세내용,소득기준 상세내용,지원내역 상세내용,특정자격 상세내용,지역거주여부 상세내용,"
    "선발방법 상세내용,선발인원 상세내용,자격제한 상세내용,추천필요여부 상세내용,제출서류 상세내용,"
    "홈페이지 주소,모집시작일,모집종료일"
)


def row(no, org, name, category, schools, grades, fields, region, start, end, support="○ 100만원"):
    cells = [str(no), org, name, "기타", "장학금", category, schools, grades, fields,
             "해당없음", "해당없음", support, "해당없음", region,
             "해당없음", "해당없음", "해당없음", "해당없음", "○ 신청서○ 재학증명서",
             "www.example.org", start, end]
    return ",".join(f'"{c}"' for c in cells)


def test_parse() -> None:
    print("파싱")
    csv_text = "\n".join([
        HEADER,
        row(1, "부산장학회", "부산 인재", "지역연고", "4년제(5~6년제포함)전문대(2~3년제)",
            "대학2학기대학3학기대학8학기이상대학신입생", "공학계열자연계열", "○ 부산 1년 이상 거주",
            "2026-10-20", "2026-11-10"),
        row(2, "전국재단", "꿈 장학생", "성적우수", "제한없음", "해당없음", "제한없음", "해당없음",
            "2026-10-01", "2026-11-05"),
    ]) + "\n" + "x" * 1000
    items = source.parse(csv_text.encode("cp949"))
    first = next(it for it in items if it["org"] == "부산장학회")
    check("CP949 를 읽고 행을 모두 꺼냄", len(items), 2)
    check("학교 구분을 자름", first["schools"], ["4년제(5~6년제포함)", "전문대(2~3년제)"])
    check("학년 구분을 자름", first["grades"], ["대학2학기", "대학3학기", "대학8학기이상", "대학신입생"])
    check("계열 구분을 자름", first["fields"], ["공학계열", "자연계열"])
    check("항목마다 줄을 나눔", first["documents"], "○ 신청서\n○ 재학증명서")
    check("주소에 http 를 붙임", first["url"], "http://www.example.org")
    again = source.parse(csv_text.replace('"1"', '"77"').encode("cp949"))
    check("행 번호가 바뀌어도 id 는 그대로", {it["id"] for it in again}, {it["id"] for it in items})


def item(org, name, start, end, *, category="기타", region="해당없음", grades=None, schools=None, fields=None):
    return {
        "id": source._key(org, name, start),
        "series": source._key(org, name),
        "org": org, "name": name, "category": category, "region": region,
        "grades": grades or ["제한없음"], "schools": schools or ["제한없음"], "fields": fields or ["제한없음"],
        "start": start, "end": end, "support": "○ 100만원", "url": "",
    }


def test_matches() -> None:
    print("내 조건")
    me = {"regions": "부산, 해운대구", "level": "재학생", "school": "전문대(2~3년제)", "field": "공학계열"}
    busan = item("부산장학회", "a", "2026-10-01", "2026-11-30", category="지역연고", region="○ 부산 거주")
    seoul = item("서대문구청", "b", "2026-10-01", "2026-11-30", category="지역연고", region="○ 서대문구 거주")
    hidden_region = item("성적재단", "c", "2026-10-01", "2026-11-30", category="성적우수",
                         region="○ 강원도에 1년 이상 거주")
    national = item("전국재단", "d", "2026-10-01", "2026-11-30", region="※ 기관확인필요")
    check("내 지역 장학금은 보임", logic.matches(me, busan), True)
    check("다른 지역 장학금은 숨김", logic.matches(me, seoul), False)
    check("유형이 지역연고가 아니어도 거주 조건이 있으면 지역으로 봄", logic.matches(me, hidden_region), False)
    check("지역 조건 없는 장학금은 늘 보임", logic.matches(me, national), True)
    check("지역을 안 정했으면 지역으로 거르지 않음", logic.matches({"regions": ""}, seoul), True)

    freshman = item("x", "e", "2026-10-01", "2026-11-30", grades=["대학신입생"])
    grad = item("x", "f", "2026-10-01", "2026-11-30", grades=["석사2학기이상", "박사과정"])
    check("재학생에게 신입생 전용은 숨김", logic.matches(me, freshman), False)
    check("재학생에게 대학원 전용은 숨김", logic.matches(me, grad), False)
    check("대학원생에게 대학원 장학금은 보임", logic.matches({"level": "대학원"}, grad), True)

    four_year = item("x", "g", "2026-10-01", "2026-11-30", schools=["4년제(5~6년제포함)"])
    some_school = item("x", "h", "2026-10-01", "2026-11-30", schools=["특정대학"])
    med = item("x", "i", "2026-10-01", "2026-11-30", fields=["의약계열"])
    some_major = item("x", "j", "2026-10-01", "2026-11-30", fields=["특정학과"])
    check("전문대생에게 4년제 전용은 숨김", logic.matches(me, four_year), False)
    check("'특정대학' 은 판단할 수 없으니 보임", logic.matches(me, some_school), True)
    check("공학계열에게 의약계열 전용은 숨김", logic.matches(me, med), False)
    check("'특정학과' 는 판단할 수 없으니 보임", logic.matches(me, some_major), True)


def test_forecast() -> None:
    print("곧 열릴 장학금")
    last_year = item("재단A", "가을 장학", "2025-11-10", "2025-11-30")
    running_now = item("재단B", "작년엔 지금 모집", "2025-10-20", "2025-11-15")
    too_far = item("재단C", "봄 장학", "2025-03-02", "2025-03-20")
    done_this_year = item("재단D", "올해 끝남", "2026-09-01", "2026-09-20")
    old_d = item("재단D", "올해 끝남", "2025-11-05", "2025-11-25")  # 작년 회차가 있어도 올해 회차가 최신
    open_now = item("재단E", "모집 중", "2026-10-20", "2026-11-20")
    old_e = item("재단E", "모집 중", "2025-10-20", "2025-11-20")
    got = logic.forecast([last_year, running_now, too_far, done_this_year, old_d, open_now, old_e], TODAY)
    check("작년 일정이 앞으로 60일 안이거나 지금 걸쳐 있는 것만", [f["org"] for f in got], ["재단B", "재단A"])
    check("예상 날짜는 작년 날짜 + 1년", (got[1]["expected_start"], got[1]["expected_end"]),
          ("2026-11-10", "2026-11-30"))


def reset_store(items) -> None:
    shutil.rmtree(store.DIR, ignore_errors=True)
    os.makedirs(store.DIR, exist_ok=True)
    store._state = None
    store._items = None
    store.replace_items(items)


def at(day: dt.date, hour: int = 10) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, tzinfo=KST)


def test_notifications() -> None:
    print("알림")
    old = item("전국재단", "있던 것", "2026-10-01", "2026-11-30")
    reset_store([old])
    store.update_settings({"discord_webhook_url": "https://discord.com/api/webhooks/1/x"})
    sent: list[dict] = []

    def fake_send(url, payload):
        sent.append(payload)

    check("첫 확인은 기준선만 잡고 아무것도 안 보냄", worker.check(at(TODAY), send=fake_send), [])
    check("기준선 뒤 변화가 없으면 조용함", worker.check(at(TODAY), send=fake_send), [])

    # 새 달 자료: 내 지역 아닌 지역 장학금 1, 전국 장학금 1, 이미 끝난 것 1
    store.update_profile({"regions": "부산"})
    fresh = item("전국재단2", "새 장학", "2026-11-01", "2026-11-20")
    other_region = item("서대문구청", "구 장학", "2026-11-01", "2026-11-20", category="지역연고",
                        region="○ 서대문구 거주")
    already_closed = item("전국재단3", "끝난 것", "2026-10-01", "2026-10-20")
    store.replace_items([old, fresh, other_region, already_closed])
    check("내 조건에 맞는 새 장학금만 묶어서 한 번", worker.check(at(TODAY), send=fake_send), ["new"])
    check("묶음에 맞는 것만 들어감", sent[-1]["embeds"][0]["title"], "🎓 내 조건에 맞는 새 장학금 1건")
    check("같은 장학금으로 다시 안 보냄", worker.check(at(TODAY), send=fake_send), [])

    # 관심: 지금 모집 중인 것 → 마감 알림, 다음 회차 → 새 회차 알림
    store.set_star(fresh["series"], True)
    check("D-17 은 아직 조용함", worker.check(at(TODAY), send=fake_send), [])
    check("D-7 에 마감 알림", worker.check(at(dt.date(2026, 11, 13)), send=fake_send), ["due"])
    check("D-6 엔 다시 안 보냄", worker.check(at(dt.date(2026, 11, 14)), send=fake_send), [])
    # 서버가 며칠 꺼져 있다가 D-1 에 켜짐: D-3 과 D-1 을 둘 다 보내지 않는다
    check("며칠 건너뛰면 가장 가까운 것 하나만", worker.check(at(dt.date(2026, 11, 19)), send=fake_send), ["due"])
    check("그 메시지는 D-1", sent[-1]["embeds"][0]["title"], "⏰ 관심 장학금 마감 D-1")
    check("D-1 을 보냈으면 마감일엔 다시 안 보냄", worker.check(at(dt.date(2026, 11, 20)), send=fake_send), [])

    store.set_star(other_region["series"], True)
    next_round = item("서대문구청", "구 장학", "2027-02-01", "2027-02-20", category="지역연고",
                      region="○ 서대문구 거주")
    store.replace_items([old, fresh, other_region, next_round])
    check("관심 장학금 새 회차는 내 조건 밖이어도 알림",
          worker.check(at(dt.date(2026, 11, 21)), send=fake_send), ["star_new"])

    # 밤에는 보내지 않고 아침에 보낸다
    late = item("전국재단4", "밤에 올라옴", "2026-11-21", "2026-12-20")
    store.replace_items([old, fresh, next_round, late])
    check("밤 11시엔 안 보냄", worker.check(at(dt.date(2026, 11, 21), 23), send=fake_send), [])
    check("아침 8시에 보냄", worker.check(at(dt.date(2026, 11, 22), 8), send=fake_send), ["new"])

    # 보내기 실패는 표시하지 않는다 → 다음에 다시 보낸다
    retry = item("전국재단5", "실패 후 재시도", "2026-11-22", "2026-12-20")
    store.replace_items([old, fresh, next_round, late, retry])

    def broken(url, payload):
        raise RuntimeError("디스코드가 거절했습니다 (HTTP 500)")

    check("실패하면 보낸 것으로 치지 않음", worker.check(at(dt.date(2026, 11, 22)), send=broken), [])
    check("실패 원인을 남김", store.snapshot()["notify_error"], "디스코드가 거절했습니다 (HTTP 500)")
    check("다음 확인 때 다시 보냄", worker.check(at(dt.date(2026, 11, 22), 11), send=fake_send), ["new"])
    check("성공하면 실패 표시를 지움", store.snapshot()["notify_error"], "")

    # 웹훅이 없을 때 쌓인 것은 나중에 웹훅을 넣어도 쏟아지지 않는다
    store.update_settings({"discord_webhook_url": ""})
    quiet_one = item("전국재단6", "웹훅 없을 때", "2026-11-22", "2026-12-20")
    store.replace_items([old, fresh, next_round, late, retry, quiet_one])
    before = len(sent)
    worker.check(at(dt.date(2026, 11, 22), 12), send=fake_send)
    store.update_settings({"discord_webhook_url": "https://discord.com/api/webhooks/1/x"})
    check("웹훅을 나중에 넣어도 밀린 알림이 안 쏟아짐",
          (worker.check(at(dt.date(2026, 11, 22), 13), send=fake_send), len(sent) - before), ([], 0))


def main() -> int:
    try:
        test_parse()
        test_matches()
        test_forecast()
        test_notifications()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    if FAILURES:
        print(f"\n실패 {len(FAILURES)}건")
        return 1
    print("\n모두 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
