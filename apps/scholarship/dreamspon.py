"""드림스폰(dreamspon.com) '일반 장학금' 모집중 목록.

드림스폰은 여러 기관의 장학 공고를 사람이 모아 올리는 곳이라 한국장학재단에 등록하지 않은
작은 재단·기업·학회 장학금이 꽤 있다. 목록과 글의 신청기간·선발인원·장학혜택 요약은
로그인 없이 보이고, 자격·원문 링크는 로그인해야 보인다. 그래서 여기서 받는 것은
기관·이름·신청기간·혜택 요약까지이고, 링크는 드림스폰 글로 건다.

  목록  /scholarship/list.html?ordby=1&page=N  (모집중, 쪽당 15건)
  글    /scholarship/view.html?idx=N

광고·후기·대출이자·이사비 같은 장학금 아닌 글이 섞여 있어서 '장학'이 들어간 것만 받는다.
한국장학재단 자료와 겹치는 것은 logic.merge 가 기관·마감일로 걸러 낸다.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
import urllib.request
from typing import Any, Callable

from . import regions

SOURCE = "드림스폰"
BASE = "https://www.dreamspon.com"
LIST_URL = BASE + "/scholarship/list.html?ordby=1&page={}"
VIEW_URL = BASE + "/scholarship/view.html?idx={}"
_UA = {"User-Agent": "Mozilla/5.0 (unifi-site scholarship)"}

MAX_PAGES = 10  # 모집중은 보통 3쪽 안팎

_SKIP_NAME = re.compile(r"꿀팁|인터뷰|MOU|후기|합격자\s*발표|할인")


class DreamsponError(Exception):
    pass


def _get(url: str, timeout: float = 30) -> str:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raise DreamsponError(f"드림스폰 응답을 읽지 못했습니다: {exc}") from exc


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_list(page: str) -> list[dict[str, Any]]:
    rows = []
    for tr in re.findall(r"(?s)<tr class=\"[^\"]*\">(.*?)</tr>", page):
        m = re.search(r'scholarship/view\.html\?idx=(\d+)"[^>]*>(.*?)</a>', tr, re.S)
        tds = re.findall(r"(?s)<td[^>]*>(.*?)</td>", tr)
        if not m or len(tds) < 2:
            continue
        rows.append({
            "idx": m.group(1),
            "name": _text(m.group(2)),
            "org": _text(tds[1]),
            "tags": [_text(t) for t in re.findall(r"<span>#([^<]*)</span>", tr)],
        })
    return rows


def has_next(page: str, no: int) -> bool:
    return f"page={no + 1}&" in page or f"page={no + 1}\"" in page


_DATE = re.compile(r"(20\d\d)\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})")


def _field(block: str, label: str) -> str:
    """'• 신청기간' 제목 다음 <p> 한 칸."""
    # 마지막 칸은 글자 수로 잘려 </p> 없이 </dd> 로 끝난다
    m = re.search(r"•\s*" + label + r".*?</p>\s*<p>(.*?)(?:</p>|</dd>|$)", block, re.S)
    return _text(m.group(1)) if m else ""


def parse_detail(page: str) -> dict[str, str]:
    """글 → {start, end, quota, benefit}. 로그인 없이 보이는 요약 칸만 읽는다."""
    i = page.find('class="scholarship04"')
    block = page[i:page.find("</dl>", i)] if i >= 0 else ""
    dates = _DATE.findall(_field(block, "신청기간"))
    days: list[str] = []
    for y, mo, d in dates:
        try:
            days.append(dt.date(int(y), int(mo), int(d)).isoformat())
        except ValueError:
            continue
    # 요약 칸이 글자 수로 잘려 '(생">' 처럼 끝난다 — 잘린 꼬리를 떼어 낸다
    quota = re.sub(r"^선발인원\s*", "", _field(block, "선발인원"))
    benefit = re.sub(r"\s*\([^)]*$|\"?>?$", "", _field(block, "장학혜택")).strip()
    return {
        "start": days[0] if len(days) > 1 else "",
        "end": days[-1] if days else "",
        "quota": "" if re.fullmatch(r"(?:총\s*0+\s*명|.*미정.*)", quota) else quota,
        "benefit": benefit,
    }


def wanted(row: dict[str, Any]) -> bool:
    if row["org"] == SOURCE or _SKIP_NAME.search(row["name"]):
        return False
    return "장학" in row["name"] or "장학금" in row["tags"]


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(p.strip() for p in parts).encode("utf-8")).hexdigest()[:12]


def to_item(row: dict[str, Any], det: dict[str, str]) -> dict[str, Any]:
    org, name, tags = row["org"], row["name"], row["tags"]
    # 지역: '#지역기준' 이 붙었거나 기관·이름에 지명이 있으면 지역 장학금으로 본다.
    # 지명을 못 찾은 지역 장학금은 '지역 확인 필요' 로 남는다(logic.place).
    regional = "지역기준" in tags or any(regions.find(f"{org} {name}"))
    support = [f"○ {label} {v}" for label, v in (("장학혜택", det["benefit"]), ("선발인원", det["quota"])) if v]
    if tags:
        support.append("○ " + " ".join("#" + t for t in tags))
    return {
        "id": _key("dreamspon", row["idx"], det["end"]),
        "series": _key(org, name),
        "org": org,
        "name": name,
        "org_type": "",
        "product": "학자금" if "대출지원" in tags else "장학금",
        "category": "지역연고" if regional else "",
        "region": f"{org} {name}" if regional else "",
        "schools": [],
        "grades": [],
        "fields": [],
        "url": VIEW_URL.format(row["idx"]),
        "start": det["start"],
        "end": det["end"],
        "support": "\n".join(support),
        "source": SOURCE,
        "aggregator": True,
    }


def fetch_list(no: int) -> str:
    return _get(LIST_URL.format(no))


def fetch_detail(idx: str) -> dict[str, str]:
    return parse_detail(_get(VIEW_URL.format(idx)))


def collect(today: dt.date, list_page: Callable[[int], str] = fetch_list,
            detail: Callable[[str], dict[str, str]] = fetch_detail, log=None) -> list[dict[str, Any]]:
    """모집중 장학금. 신청기간을 못 읽은 글은 넣지 않는다(지금 받는지 알 수 없다)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for no in range(1, MAX_PAGES + 1):
        page = list_page(no)
        rows = parse_list(page)
        if no == 1 and not rows:
            raise DreamsponError("드림스폰 목록을 읽지 못했습니다 (화면 형식이 바뀐 것 같습니다)")
        for row in rows:
            if row["idx"] in seen or not wanted(row):
                continue
            seen.add(row["idx"])
            try:
                det = detail(row["idx"])
            except DreamsponError as exc:
                if log:
                    log.warning("드림스폰 글 %s 를 못 읽음: %s", row["idx"], exc)
                continue
            end = dt.date.fromisoformat(det["end"]) if det["end"] else None
            if not end or end < today:
                continue
            out.append(to_item(row, det))
        if not rows or not has_next(page, no):
            break
    return out
