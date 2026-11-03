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


def is_regional(item: dict[str, Any]) -> bool:
    return item.get("category") == "지역연고" or not _NO_REGION.match(item.get("region") or "")


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


def matches(profile: dict[str, Any], item: dict[str, Any]) -> bool:
    words = region_words(profile)
    if words and is_regional(item):
        hay = f"{item.get('org', '')} {item.get('region', '')}"
        if not any(w in hay for w in words):
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
