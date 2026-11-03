"""한국장학재단 학생지원 포털의 '학자금 지원정보 통합검색(대학생)' — 실시간 목록.

공공데이터포털 CSV(source.py)와 같은 원본인데 CSV 는 한 달에 한 번 나온다.
포털은 재단이 등록하는 즉시 보이므로, 최근 등록순 몇 쪽만 읽어 CSV 에 아직 없는
장학금을 채운다. 로그인·쿠키·토큰 없이 POST 한 번이면 된다.

  목록  getItgnSrchCstmDsgnGoodsList (sorting=05 최근등록일순, 쪽당 10건)
  상세  getCstmDsgnGoodsDtl (cstmDsgnGoodsCd) — CSV 와 같은 항목(신청기간·지원금액·자격…)

응답이 쪽마다 1MB 넘는 HTML 이라 CSV 에 이미 있는 행이 계속 나오면 거기서 멈춘다.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import urllib.parse
import urllib.request
from typing import Any, Callable

from . import source

URL = "https://portal.kosaf.go.kr/CO/jspAction.do"
_BASE = {
    "beanName": "PTSMCstmDsgnGoodsSVC",
    "forwardOnlyFlag": "N",
    "ignoreSession": "Y",
    "innerFlag": "Y",
}
_UA = {"User-Agent": "Mozilla/5.0 (unifi-site scholarship)"}

MAX_PAGES = 15
STOP_AFTER_KNOWN_PAGES = 2  # CSV 에 다 있는 쪽이 이만큼 이어지면 그 뒤는 CSV 가 갖고 있다


def _post(params: dict[str, str], timeout: float = 60) -> str:
    body = urllib.parse.urlencode({**_BASE, **params}).encode()
    req = urllib.request.Request(URL, data=body, headers=_UA, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raise source.SourceError(f"한국장학재단 포털 응답을 읽지 못했습니다: {exc}") from exc


def _cell(fragment: str) -> str:
    fragment = re.sub(r"(?i)</li>|<br\s*/?>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return "\n".join(re.sub(r"[ \t\r\xa0]+", " ", ln).strip() for ln in text.splitlines() if ln.strip())


def parse_list(page: str) -> list[dict[str, str]]:
    rows = []
    for tr in re.findall(r"(?s)<tr>(.*?)</tr>", page):
        m = re.search(r"fn_goDtl\('(\d+)'\)", tr)
        if not m:
            continue
        tds = [_cell(td) for td in re.findall(r"(?s)<td[^>]*>(.*?)</td>", tr)]
        if len(tds) < 7:
            continue
        rows.append({"code": m.group(1), "org": tds[1], "name": tds[2], "end": tds[6][:10]})
    return rows


def fetch_list(no: int) -> list[dict[str, str]]:
    return parse_list(_post({
        "methodName": "getItgnSrchCstmDsgnGoodsList",
        "inputVOName": "kr.go.kosaf.portal.pt.sm.cstmdsgngoods.svc.PTSMCstmDsgnGoodsSVO",
        "forwardPage": "pt/sm/cstmdsgngoods/PTSMCstmDsgnGoods_10M",
        "no": str(no),
        "sorting": "05",
    }))


# 상세 화면의 칸 이름 → CSV 열 이름. 같은 이름으로 맞춰 두면 source.py 의 정리 규칙을 그대로 쓴다.
_LABELS = {
    "상품구분": "상품구분",
    "운영기관구분": "운영기관구분",
    "운영기관명": "운영기관명",
    "홈페이지주소": "홈페이지 주소",
    "대학구분": "대학구분",
    "학년구분": "학년구분",
    "학과구분": "학과구분",
    "성적기준": "성적기준 상세내용",
    "소득기준": "소득기준 상세내용",
    "지원금액": "지원내역 상세내용",
    "특정자격": "특정자격 상세내용",
    "지역거주구분": "지역거주여부 상세내용",
    "신청기간": "신청기간",
    "선발방법": "선발방법 상세내용",
    "선발인원": "선발인원 상세내용",
    "자격제한": "자격제한 상세내용",
    "추천필요여부": "추천필요여부 상세내용",
    "제출처 및 제출서류": "제출서류 상세내용",
}


def parse_detail(page: str) -> dict[str, str]:
    """상세 화면 → CSV 한 행과 같은 모양의 dict."""
    start = page.find('id="content_wrap"')
    block = page[start:page.find("</table>", start)] if start >= 0 else ""
    title = re.search(r'(?s)<h4 class="bg_title"><span>(.*?)</span>', block)
    cells = [_cell(c) for c in re.findall(r"(?s)<t[hd][^>]*>(.*?)</t[hd]>", block)]
    row: dict[str, str] = {"상품명": _cell(title.group(1)) if title else ""}
    for i, c in enumerate(cells[:-1]):
        col = _LABELS.get(c)
        if col and col not in row:
            row[col] = cells[i + 1]
    # 목록형 칸(대학·학년·학과)은 줄마다 하나 — CSV 처럼 붙여 두면 같은 어휘 분리기가 먹는다
    for col in ("대학구분", "학년구분", "학과구분"):
        row[col] = row.get(col, "").replace("\n", "")
    period = re.findall(r"\d{4}-\d{2}-\d{2}", row.pop("신청기간", ""))
    row["모집시작일"] = period[0] if period else ""
    row["모집종료일"] = period[-1] if period else ""
    return row


def fetch_detail(code: str) -> dict[str, str]:
    return parse_detail(_post({
        "methodName": "getCstmDsgnGoodsDtl",
        "inputVOName": "kr.go.kosaf.portal.pt.sm.cstmdsgngoods.svc.PTSMCstmDsgnGoodsDtlSVO",
        "forwardPage": "pt/sm/cstmdsgngoods/PTSMCstmDsgnGoods_02M",
        "cstmDsgnGoodsCd": code,
    }))


def to_item(row: dict[str, str]) -> dict[str, Any] | None:
    """CSV 행을 고르는 source.parse 를 그대로 태운다 — 같은 장학금이면 같은 id·series 가 나온다."""
    import csv
    import io

    cols = ["운영기관명", "상품명", "운영기관구분", "상품구분", "학자금유형구분", "대학구분", "학년구분",
            "학과구분", "홈페이지 주소", "모집시작일", "모집종료일", *source._TEXT_COLUMNS]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerow({c: row.get(c, "") for c in cols})
    items = source.parse(buf.getvalue().encode("utf-8-sig"))
    return items[0] if items else None


def collect(known: set[tuple[str, str, str]], cache: dict[str, dict[str, Any]], today: dt.date,
            list_page: Callable[[int], list[dict[str, str]]] = fetch_list,
            detail: Callable[[str], dict[str, str]] = fetch_detail) -> list[dict[str, Any]]:
    """CSV 에 아직 없는 최근 장학금. known 은 CSV 의 (기관, 이름, 마감일).
    cache 는 상세를 이미 받아 둔 것(code|마감일 → item) — 갱신마다 다시 받지 않는다. 제자리에서 고친다."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    known_run = 0
    for no in range(1, MAX_PAGES + 1):
        rows = list_page(no)
        if not rows:
            break
        fresh = [r for r in rows if (r["org"], r["name"], r["end"]) not in known]
        known_run = 0 if fresh else known_run + 1
        if known_run >= STOP_AFTER_KNOWN_PAGES:
            break
        for r in fresh:
            key = f"{r['code']}|{r['end']}"
            if key in seen:
                continue
            seen.add(key)
            end = _date(r["end"])
            if end and (today - end).days > 60:
                continue  # 오래 지난 것은 굳이 상세를 받지 않는다
            if key not in cache:
                item = to_item(detail(r["code"]))
                if not item:
                    continue
                item["source"] = "한국장학재단 포털"
                cache[key] = item
            out.append(cache[key])
    return out


def _date(text: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None
