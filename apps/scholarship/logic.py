"""판정 로직 — 네트워크·파일 없이 돌아가는 순수 함수만 둔다(테스트 대상).

- 모집 상태와 D-day
- 내 조건에 맞는지
- 작년 일정으로 본 '작년 일정 참고' 장학금 (올해 모집은 미확인)
- 보낼 알림 고르기
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from . import regions

OPEN_TOKENS = {"제한없음", "해당없음"}
LEVELS = ("신입생", "재학생", "대학원")

# 지역 칸이 이렇게만 적혀 있으면 지역 조건이 없는 것으로 본다
_NO_REGION = re.compile(r"^\s*(해당없음|제한없음|※\s*기관\s*확인\s*필요)?\s*$")


def parse_date(text: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat((text or "")[:10])
    except ValueError:
        return None


# 공고 기간이 이만큼 길면 '신청 기간' 이 아니라 사업 기간일 때가 많다.
# 예: 국가근로장학금은 2026-03-01~2027-02-28 로 올라오지만 실제 신청은
# 학기마다 한 달쯤만 받는다(2026년 2학기는 9/9 마감). 이런 건 '신청 가능' 으로
# 단정하지 않고 '연중 사업' 으로 따로 보여 준다.
YEAR_ROUND_DAYS = 300


def status(item: dict[str, Any], today: dt.date) -> str:
    """upcoming | open | year_round | closed"""
    start, end = parse_date(item.get("start", "")), parse_date(item.get("end", ""))
    if start and today < start:
        return "upcoming"
    if end and today > end:
        return "closed"
    if start and end and (end - start).days >= YEAR_ROUND_DAYS:
        return "year_round"
    return "open"


def dday(item: dict[str, Any], today: dt.date) -> int | None:
    end = parse_date(item.get("end", ""))
    return (end - today).days if end else None


# ---------------- 내 조건 ----------------
def region_words(profile: dict[str, Any]) -> list[str]:
    return [w.strip() for w in re.split(r"[,\s]+", profile.get("regions") or "") if w.strip()]


# 자격 칸에서 지역 조건으로 읽을 문장 — 지명 옆에 이런 말이 있어야 한다
_RESIDENCY = re.compile(r"소재|거주|주민등록|시민|도민|군민|구민|출신|관내|주소")


def _special_places(item: dict[str, Any]) -> tuple[set[str], set[str]]:
    """'서울 소재 대학 재학생' 처럼 지역 조건을 자격 칸에 적은 공고가 꽤 있다."""
    sido: set[str] = set()
    sigungu: set[str] = set()
    for line in (item.get("special") or "").splitlines():
        if _RESIDENCY.search(line):
            a, b = regions.find(line)
            sido |= a
            sigungu |= b
    return sido, sigungu


def place(item: dict[str, Any]) -> tuple[str, set[str], set[str]]:
    """장학금의 거주 조건 → (종류, 시·도, 시·군·구).

    종류는 national(지역 무관) / places(어디인지 앎) / unknown(지역 조건은 있는데 어디인지 모름).
    읽는 순서: 지역 칸 → (전국이라고 적혀 있으면 지역 무관) → 자격 칸의 '○○ 소재·거주'
    → 기관명('관내 거주' + '경상북도 의성군청'). 기관명은 지역 칸에 조건이 있거나
    유형이 지역연고일 때만 본다('부산은행 장학재단' 이 전국을 뽑을 수 있다).
    """
    text = item.get("region") or ""
    regional = item.get("category") == "지역연고" or not _NO_REGION.match(text)
    org_sido, org_sigungu = regions.find(item.get("org") or "")
    sido, sigungu = regions.find(text)
    if sido or sigungu:
        if not sido:
            sido = set(org_sido)  # '동구 관내 거주' + '(재)대구동구교육재단'
    elif "전국" in text:
        return "national", set(), set()
    else:
        sido, sigungu = _special_places(item)
        if not sido and not sigungu and regional:
            sido, sigungu = org_sido, org_sigungu
    sido |= regions.sido_of(sigungu)
    if sido or sigungu:
        return "places", sido, sigungu
    return ("unknown" if regional else "national"), set(), set()


def is_regional(item: dict[str, Any]) -> bool:
    return place(item)[0] != "national"


def region_verdict(profile: dict[str, Any], item: dict[str, Any]) -> str:
    """ok(내 지역) / no(다른 지역) / unknown(지역 장학금인데 판단 못 함) / na(지역 무관·지역 미입력)."""
    words = region_words(profile)
    kind, sido, sigungu = place(item)
    if not words or kind == "national":
        return "na"

    my_sido: set[str] = set()
    my_sigungu: set[str] = set()
    free: list[str] = []
    for w in words:
        level, value = regions.classify_word(w)
        if level == "sido":
            my_sido.add(value)
        elif level == "sigungu":
            my_sigungu.add(value)
        else:
            free.append(value)
    my_sido |= regions.sido_of(my_sigungu)

    hay = f"{item.get('org', '')} {item.get('region', '')}"
    if any(w in hay for w in free):
        return "ok"
    if kind == "unknown":
        # '횡성에 주소' 처럼 시·군을 줄여 적은 공고는 내 시·군 이름 앞부분으로 한 번 더 본다.
        stems = [n[:-1] for n in my_sigungu if n.endswith(("시", "군")) and len(n) >= 3]
        return "ok" if any(st in hay for st in stems) else "unknown"
    # 공고가 적은 단계마다 내 것과 맞아야 한다. '부산 수영구' 는 '부산, 해운대구' 와 안 맞는다.
    if sido and my_sido and not sido & my_sido:
        return "no"
    if sigungu and my_sigungu and not sigungu & my_sigungu:
        return "no"
    if sido & my_sido or sigungu & my_sigungu:
        return "ok"
    return "unknown"


def _level_ok(level: str, grades: list[str]) -> bool:
    if not level or not grades or OPEN_TOKENS & set(grades) or set(grades) <= {"연령제한"}:
        return True
    if level == "신입생":
        return "대학신입생" in grades
    if level == "재학생":
        return any(g.startswith("대학") and g.endswith(("학기", "학기이상")) for g in grades)
    if level == "대학원":
        return any(g.startswith(("석사", "박사")) for g in grades)
    return True


def _pick_ok(choice: str, tokens: list[str], unknown: str) -> bool:
    """학교·계열. '특정대학/특정학과' 는 우리가 판단할 수 없으니 통과시킨다."""
    if not choice or not tokens:
        return True
    return choice in tokens or bool((OPEN_TOKENS | {unknown}) & set(tokens))


# ---------------- 지원 용도 / 대출 ----------------
# 지원 내용에 이런 말이 있으면 생활비로 쓰는 돈이다. 근로·멘토링 장학금은 시급으로 받는다.
_LIVING = re.compile(
    r"생활비|생활\s*장학|생활\s*지원|생활안정|생활보조|생활자금|생계|주거|월세|교통비|자기계발|도서구입"
    r"|학업장려|학업보조|학습장려|장려금|활동비|활동지원금|시급"
)
_TUITION = re.compile(r"등록금|수업료|입학금|학비")
_LOAN = re.compile(r"대출|대부|융자")


# '생활비 지원 불가', '생활비는 제외' 처럼 부정하는 말은 생활비로 세지 않는다
_NEGATED = re.compile(
    "(?:" + _LIVING.pattern + r")[^○※\n]{0,12}?(?:불가|제외|미지원|불포함|지원\s*안|지원하지\s*않|해당\s*없|아님)"
)


def purpose(item: dict[str, Any]) -> str:
    """living(생활비가 들어 있음) / tuition(등록금 전용) / unclear(금액만 적힘).

    지원 내용을 기준으로 본다. 이름('학업장려 장학금')은 지원 내용에 용도가 전혀
    안 적혀 있을 때만 본다 — 이름이 그래도 실제로는 등록금으로 주는 경우가 있다.
    """
    support = _NEGATED.sub(" ", item.get("support") or "")
    if _LIVING.search(support):
        return "living"
    if _TUITION.search(support):
        return "tuition"
    name = _NEGATED.sub(" ", item.get("name") or "")
    if _LIVING.search(name):
        return "living"
    if _TUITION.search(name):
        return "tuition"
    return "unclear"


def is_loan(item: dict[str, Any]) -> bool:
    """한국장학재단은 대출·대출이자 지원을 상품구분 '학자금' 으로 따로 둔다."""
    return item.get("product") == "학자금" or bool(_LOAN.search(item.get("name") or ""))


def _purpose_ok(choice: str, item: dict[str, Any]) -> bool:
    if choice == "living":
        return purpose(item) == "living"
    if choice == "no_tuition":
        return purpose(item) != "tuition"
    return True


def excluded(profile: dict[str, Any], item: dict[str, Any]) -> bool:
    """대출·지원 용도는 사용자가 '이건 아예 안 받겠다' 고 정한 것이다.
    관심 표시와 상관없이 목록에서도 알림에서도 뺀다."""
    if profile.get("exclude_loans", True) and is_loan(item):
        return True
    return not _purpose_ok(profile.get("purpose", ""), item)


def matches(profile: dict[str, Any], item: dict[str, Any]) -> bool:
    """내 조건에 맞는가. 지역은 내 지역이거나 전국인 것만 — 어느 읍·면 것인지 모르는
    장학금은 대부분 남의 동네 것이라 뺀다('내 조건만' 을 끄면 '지역 확인 필요' 로 보인다)."""
    if excluded(profile, item):
        return False
    if region_verdict(profile, item) in ("no", "unknown"):
        return False
    return (
        _level_ok(profile.get("level", ""), item.get("grades") or [])
        and _pick_ok(profile.get("school", ""), item.get("schools") or [], "특정대학")
        and _pick_ok(profile.get("field", ""), item.get("fields") or [], "특정학과")
    )


# ---------------- 작년 일정 참고 (올해 모집 미확인) ----------------
def _plus_year(d: dt.date) -> dt.date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 2월 29일
        return d.replace(year=d.year + 1, day=28)


def latest_rounds(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """장학금(series)마다 가장 최근 회차."""
    latest: dict[str, dict[str, Any]] = {}
    for it in items:
        cur = latest.get(it["series"])
        if cur is None or it.get("start", "") > cur.get("start", ""):
            latest[it["series"]] = it
    return latest


def forecast(items: Iterable[dict[str, Any]], today: dt.date, horizon: int = 60) -> list[dict[str, Any]]:
    """작년 일정으로 보면 앞으로 열릴 장학금(올해 회차는 아직 목록에 없는 것).

    작년 기준으로 이미 모집이 시작됐을 것은 넣지 않는다. 원본에 올해 회차가
    없다고 아직 안 열린 게 아니다 — 재단이 일정을 몇 주 당기거나(한국고등교육재단
    인재림: 작년 10/28~11/24 → 올해 10/8~10/29), 학교 추천 마감이 재단보다
    빠르거나(한국지도자육성장학재단: 학교 마감 10/26~10/30), 원본에 아예 안
    올라오는 경우가 많아서, 이런 걸 넣으면 대부분 이미 끝난 것이 된다.
    남은 것도 올해 모집이 확인된 것은 아니므로 화면에는 '작년 일정 참고' 로만 보여 준다.
    """
    out = []
    for it in latest_rounds(items).values():
        start, end = parse_date(it.get("start", "")), parse_date(it.get("end", ""))
        if not start or not end or end >= today:
            continue  # 지금 회차가 살아 있거나 날짜가 없다
        if (today - start).days < 300:
            continue  # 올해 회차가 이미 끝난 것 — 다음은 내년
        exp_start, exp_end = _plus_year(start), _plus_year(end)
        if exp_start <= today or exp_start > today + dt.timedelta(days=horizon):
            continue
        out.append({**it, "expected_start": exp_start.isoformat(), "expected_end": exp_end.isoformat()})
    out.sort(key=lambda x: x["expected_start"])
    return out


# ---------------- 알림 고르기 ----------------
def plan_notifications(
    items: list[dict[str, Any]],
    *,
    profile: dict[str, Any],
    settings: dict[str, Any],
    stars: list[str],
    known_ids: set[str],
    sent: set[str],
    today: dt.date,
) -> list[dict[str, Any]]:
    """보낼 알림 목록. 각 항목은 {kind, keys, items, ...}.

    - star_new : 관심 장학금에 새 회차가 올라왔다 (지역·학년 조건과 상관없이,
                 단 대출·지원 용도로 뺀 것은 관심이어도 보내지 않는다)
    - new      : 내 조건에 맞는 새 장학금 묶음 (한 번에 하나의 메시지)
    - due      : 관심 장학금 마감 임박
    'keys' 는 보낸 뒤 sent 에 넣어 다시 보내지 않게 하는 표식이다.
    """
    star_set = set(stars)
    out: list[dict[str, Any]] = []
    live = [it for it in items if status(it, today) != "closed" and not excluded(profile, it)]
    fresh = [it for it in live if it["id"] not in known_ids]

    starred_new = []
    if settings.get("notify_starred", True):
        starred_new = [it for it in fresh if it["series"] in star_set and f"star_new:{it['id']}" not in sent]
        for it in starred_new:
            out.append({"kind": "star_new", "keys": [f"star_new:{it['id']}"], "items": [it]})

    if settings.get("notify_new", True):
        taken = {it["id"] for it in starred_new}
        batch = [
            it for it in fresh
            if it["id"] not in taken and f"new:{it['id']}" not in sent and matches(profile, it)
        ]
        if batch:
            batch.sort(key=lambda it: it.get("end", ""))
            out.append({"kind": "new", "keys": [f"new:{it['id']}" for it in batch], "items": batch})

    if settings.get("notify_starred", True):
        thresholds = sorted({int(d) for d in settings.get("reminder_days") or [] if int(d) >= 0})
        for it in live:
            if it["series"] not in star_set or status(it, today) != "open":
                continue
            left = dday(it, today)
            hit = [t for t in thresholds if left is not None and left <= t]
            if not hit:
                continue
            key = f"due:{it['id']}:{hit[0]}"
            if key in sent:
                continue
            # 며칠 건너뛰었으면 가장 가까운 것 하나만 보내고 큰 것들은 같이 지운다.
            keys = [f"due:{it['id']}:{t}" for t in hit]
            out.append({"kind": "due", "keys": keys, "items": [it], "dday": left})
    return out
