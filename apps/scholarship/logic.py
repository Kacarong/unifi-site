"""판정 로직 — 네트워크·파일 없이 돌아가는 순수 함수만 둔다(테스트 대상).

- 모집 상태와 D-day
- 내 조건에 맞는지
- 작년 일정으로 본 '곧 열릴' 장학금
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


def status(item: dict[str, Any], today: dt.date) -> str:
    start, end = parse_date(item.get("start", "")), parse_date(item.get("end", ""))
    if start and today < start:
        return "upcoming"
    if end and today > end:
        return "closed"
    return "open"


def dday(item: dict[str, Any], today: dt.date) -> int | None:
    end = parse_date(item.get("end", ""))
    return (end - today).days if end else None


# ---------------- 내 조건 ----------------
def region_words(profile: dict[str, Any]) -> list[str]:
    return [w.strip() for w in re.split(r"[,\s]+", profile.get("regions") or "") if w.strip()]


def place(item: dict[str, Any]) -> tuple[str, set[str], set[str]]:
    """장학금의 거주 조건 → (종류, 시·도, 시·군·구).

    종류는 national(지역 무관) / places(어디인지 앎) / unknown(지역 조건은 있는데 어디인지 모름).
    거주 조건 칸을 먼저 읽는다. 거기에 지명이 없을 때만 기관명을 본다
    ('관내 거주' + '경상북도 의성군청'). '○ 전국' 처럼 전국이라고만 적혀 있으면
    기관명에 지명이 있어도 지역 무관이다('부산은행 장학재단' 이 전국을 뽑을 수 있다).
    """
    text = item.get("region") or ""
    if _NO_REGION.match(text) and item.get("category") != "지역연고":
        return "national", set(), set()
    sido, sigungu = regions.find(text)
    org_sido, org_sigungu = regions.find(item.get("org") or "")
    if not sido and not sigungu:
        if "전국" in text:
            return "national", set(), set()
        sido, sigungu = org_sido, org_sigungu
    elif not sido:
        sido = set(org_sido)  # '동구 관내 거주' + '(재)대구동구교육재단'
    sido |= regions.sido_of(sigungu)
    if not sido and not sigungu:
        return "unknown", set(), set()
    return "places", sido, sigungu


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


def matches(profile: dict[str, Any], item: dict[str, Any], strict: bool = False) -> bool:
    """목록에서는 다른 지역이 확실할 때만 뺀다. 판단 못 한 지역 장학금은 '지역 확인 필요'
    로 보여 준다. 알림(strict)에서는 그것까지 뺀다. 어느 읍·면 장학금인지 모르는 것을
    새 장학금이라고 보내면 대부분 남의 동네 것이다."""
    verdict = region_verdict(profile, item)
    if verdict == "no" or (strict and verdict == "unknown"):
        return False
    return (
        _level_ok(profile.get("level", ""), item.get("grades") or [])
        and _pick_ok(profile.get("school", ""), item.get("schools") or [], "특정대학")
        and _pick_ok(profile.get("field", ""), item.get("fields") or [], "특정학과")
    )


# ---------------- 곧 열릴 장학금 ----------------
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
    """작년 이맘때 모집했는데 올해 회차가 아직 안 올라온 장학금.

    원본이 한 달에 한 번 갱신되므로 이미 모집이 시작됐는데 목록에만 아직 없는
    경우도 있다. 그래서 '작년 기준으로 지금 모집 중이었을' 것도 같이 보여 준다.
    """
    out = []
    for it in latest_rounds(items).values():
        start, end = parse_date(it.get("start", "")), parse_date(it.get("end", ""))
        if not start or not end or end >= today:
            continue  # 지금 회차가 살아 있거나 날짜가 없다
        if (today - start).days < 300:
            continue  # 올해 회차가 이미 끝난 것 — 다음은 내년
        exp_start, exp_end = _plus_year(start), _plus_year(end)
        if exp_end < today or exp_start > today + dt.timedelta(days=horizon):
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

    - star_new : 관심 장학금에 새 회차가 올라왔다 (내 조건과 상관없이)
    - new      : 내 조건에 맞는 새 장학금 묶음 (한 번에 하나의 메시지)
    - due      : 관심 장학금 마감 임박
    'keys' 는 보낸 뒤 sent 에 넣어 다시 보내지 않게 하는 표식이다.
    """
    star_set = set(stars)
    out: list[dict[str, Any]] = []
    live = [it for it in items if status(it, today) != "closed"]
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
            if it["id"] not in taken and f"new:{it['id']}" not in sent and matches(profile, it, strict=True)
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
