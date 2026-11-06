"""공고 게시판 — 대한토목학회·재단 홈페이지에 올라온 장학생 모집 글.

한국장학재단 자료에는 늦게 올라오거나 아예 안 올라오는 공고가 있다. 게시판 목록에서
'장학 + 모집/선발' 제목을 고르고, 글 본문에서 신청 기간을 읽는다. 본문에 없으면
첨부 공고문(HWP/HWPX/PDF/ZIP)을 내려받아 그 안에서 읽는다(docs.py).

게시판마다 HTML 이 달라서 목록은 넓게 읽는다: 표의 한 행(<tr>)이나 목록의 한 칸(<li>)
안에 글 링크와 날짜가 같이 있으면 그것을 글 하나로 본다. 링크가 onclick 으로만 있는
곳(신한·DB 등)은 아직 넣지 않았다 — 그 재단들은 한국장학재단 실시간 목록에 올라온다.

인스타그램·페이스북은 로그인 없이는 글을 볼 수 없어 넣지 않았다.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import http.cookiejar
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from typing import Any

from . import docs

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

# org 는 한국장학재단 자료의 기관명과 맞춰 둔다 — 같은 기관의 장학금으로 묶는 데 쓴다(logic.merge).
BOARDS: list[dict[str, Any]] = [
    {
        "id": "ksce_news",
        "label": "대한토목학회 토목계소식",
        "org": "대한토목학회",
        "bracket_org": True,  # '[엔지니어링인재육성재단] …' — 외부 기관 공고를 대신 올린다
        "url": "https://www.ksce.or.kr/not/default.asp?gbn=10&htop=MN0031&ctop=MN0096&ptop=MN0031&sfield=2&gtxt=%EC%9E%A5%ED%95%99",
    },
    {
        "id": "ksce_notice",
        "label": "대한토목학회 공지사항",
        "org": "대한토목학회",
        "bracket_org": True,
        "url": "https://www.ksce.or.kr/not/default.asp?gbn=6&htop=MN0031&ctop=MN0048&ptop=MN0031&sfield=2&gtxt=%EC%9E%A5%ED%95%99",
    },
    # 학교 게시판은 검색어('장학')로 이미 걸러져 있고 제목이 '○○ 장학금' 처럼 짧아서
    # '모집·선발' 낱말이 없어도 받는다(loose). 대신 게시일이 있는 글만.
    {
        "id": "pknu_civil",
        "label": "부경대 토목공학과",
        "org": "부경대학교 토목공학과",
        "url": "https://civil.pknu.ac.kr/civil/5346?pageIndex=1&bbsId=2402698&searchCondition=title&searchKeyword=%EC%9E%A5%ED%95%99",
        "loose": True,
    },
    {
        "id": "pknu_main",
        "label": "부경대 등록·장학 공지",
        "org": "부경대학교",
        "url": "https://www.pknu.ac.kr/main/163?cd=10004",
        "loose": True,
    },
    {
        "id": "yonkang",
        "label": "두산연강재단",
        "org": "두산연강재단",
        "url": "https://www.yonkang.org/kr/support/information/",
    },
    {
        "id": "daeeun",
        "label": "대은강완석장학재단",
        "org": "대은강완석장학재단",
        "url": "http://shop.daeeunsf.org/bbs/board.php?bo_table=notice",
    },
    {
        "id": "miraenanum",
        "label": "미래나눔재단",
        "org": "미래나눔재단",
        "url": "http://www.miraenanum.org/bbs/board.php?bo_table=notice",
    },
    {
        "id": "wooyang",
        "label": "재단법인 우양",
        "org": "재단법인 우양",
        "url": "https://www.wooyang.org/News",
    },
    {
        "id": "inseok",
        "label": "인석장학회",
        "org": "인석장학회",
        "url": "https://www.inseok.org/board5/bbs/board.php?bo_table=notice_1",
    },
]

def all_sources(state: dict[str, Any]) -> list[dict[str, Any]]:
    """기본 게시판 + 사용자가 더한 게시판. 각각 enabled·builtin 표시를 붙인다."""
    off = set(state.get("sources_off") or [])
    out = [{**b, "builtin": True} for b in BOARDS]
    out += [{"org": c.get("label", ""), **c, "builtin": False} for c in state.get("custom_sources") or []]
    return [{**b, "enabled": b["id"] not in off} for b in out]


def active_sources(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for b in all_sources(state) if b["enabled"]]


def probe(url: str, today: dt.date | None = None) -> dict[str, Any]:
    """게시판 주소를 더하기 전에 한 번 읽어 본다 — 글 목록을 찾았는지, 장학 글이 몇 개인지."""
    today = today or dt.date.today()
    f = Fetcher()
    data, final_url, ctype = f.get(url)
    page = decode_html(data, ctype)
    posts = list_posts(page, final_url)
    dated = [p for p in posts if p["posted"]]
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    return {
        "posts": len(dated),
        "scholarship": [clean_title(p["title"]) for p in pick({"loose": True}, posts, today)][:5],
        "title": _text(title.group(1))[:60] if title else "",
    }


# 제목 고르기
_WANT = re.compile(r"장학")
_RECRUIT = re.compile(r"모집|선발|공고|공모|추천|신청")
_SKIP = re.compile(
    r"결과|발표|합격|명단|수여식|증서|기부금|후기|수기|간담회|워크숍|연구|논문|채용|입찰"
    r"|지급|납부|분할|서식|양식|변경사항|반환|환수|정정|연장 안내|만족도|설문"
)

_DATE_IN_ROW = re.compile(r"(20\d\d)\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})")
_DOWNLOAD = re.compile(r"download|file_?down|filedown|fileDown|down\.php|/file/down|atchFile|\.(?:hwp|hwpx|pdf|zip)\b", re.I)

RECENT_DAYS = 150     # 이보다 오래된 글은 지난 회차라 보지 않는다
MAX_POSTS = 8         # 게시판 하나에서 열어 보는 글 수
CLOSED_KEEP_DAYS = 180  # 마감이 이보다 오래 지난 공고는 버린다 ('최근 마감' 탭과 같은 기간)
MAX_FILES = 4         # 글 하나에서 받아 보는 첨부 수


class BlockedURL(ValueError):
    pass


def check_public_url(url: str) -> None:
    """사용자가 넣은 게시판 주소로 서버 안쪽(127.0.0.1, 사설망)을 찌르지 못하게 한다."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedURL("http(s) 주소만 넣을 수 있습니다")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise BlockedURL(f"주소를 찾을 수 없습니다: {parts.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise BlockedURL("내부망 주소는 넣을 수 없습니다")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        check_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    """쿠키를 기억하는 받기 도구. 글을 먼저 열어야 첨부가 받아지는 게시판(그누보드)이 있다.
    공개 주소만 받는다 — 게시판은 사이트에서 사용자가 더할 수 있다."""

    def __init__(self, timeout: float = 25) -> None:
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _SafeRedirect()
        )

    def get(self, url: str, referer: str = "") -> tuple[bytes, str, str]:
        headers = {"User-Agent": _UA, "Accept-Language": "ko-KR,ko;q=0.9"}
        if referer:
            headers["Referer"] = referer
        # 한글이 섞인 주소('&gtxt=장학')는 그대로 보내면 urllib 가 못 보낸다
        url = urllib.parse.quote(url, safe=":/?&=%#+,;@!$'()*~[]")
        check_public_url(url)
        req = urllib.request.Request(url, headers=headers)
        with self.opener.open(req, timeout=self.timeout) as resp:
            data = resp.read(docs.MAX_FILE_BYTES + 1)
            return data, resp.geturl(), resp.headers.get("Content-Type", "")


def decode_html(data: bytes, content_type: str = "") -> str:
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I) or re.search(
        rb"<meta[^>]+charset=[\"']?([\w-]+)", data[:4000], re.I
    )
    enc = m.group(1) if m else "utf-8"
    if isinstance(enc, bytes):
        enc = enc.decode("ascii", "ignore")
    enc = enc.lower()
    if enc in ("euc-kr", "ks_c_5601-1987", "x-windows-949"):
        enc = "cp949"
    try:
        return data.decode(enc, "replace")
    except LookupError:
        return data.decode("utf-8", "replace")


def _unescape_url(href: str) -> str:
    """html.unescape 는 '&gtxt=' 를 '>xt=' 로 바꿔 버린다(세미콜론 없는 옛 엔티티). 주소는 &amp; 만 푼다."""
    return re.sub(r"&(?:amp|#0*38);", "&", href)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def list_posts(page: str, base_url: str) -> list[dict[str, Any]]:
    """목록 HTML → [{title, url, posted}]. 같은 주소는 한 번만."""
    page = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    chunks = re.findall(r"(?is)<tr[\s>].*?</tr>|<li[\s>].*?</li>|<article[\s>].*?</article>", page)
    seen: set[str] = set()
    out = []
    for chunk in chunks:
        if len(chunk) > 6000:  # 메뉴 전체를 감싼 바깥 <li>
            continue
        date = _DATE_IN_ROW.search(_text(chunk))
        best = None
        for a in re.finditer(r"(?is)<a\b([^>]*)>(.*?)</a>", chunk):
            attrs, inner = a.group(1), a.group(2)
            title = _text(inner) or _text(re.search(r'title="([^"]*)"', attrs).group(1) if 'title="' in attrs else "")
            if len(title) < 6:
                continue
            href = ""
            m = re.search(r'href\s*=\s*"([^"]*)"', attrs) or re.search(r"href\s*=\s*'([^']*)'", attrs)
            if m and not m.group(1).lower().startswith(("javascript", "#")):
                href = _unescape_url(m.group(1))
            if not href:
                continue
            if best is None or len(title) > len(best[0]):
                best = (title, href)
        if not best:
            continue
        url = urllib.parse.urljoin(base_url, best[1])
        if url in seen:
            continue
        seen.add(url)
        posted = None
        if date:
            try:
                posted = dt.date(int(date.group(1)), int(date.group(2)), int(date.group(3)))
            except ValueError:
                posted = None
        out.append({"title": best[0], "url": url, "posted": posted})
    return out


_POSTED_IN_PAGE = re.compile(
    r"(?:작성일|등록일|게시일|작성일시|등록일시)\S*\s*[:：]?\s*((?:20)?\d\d)\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})"
)


def posted_in_page(text: str) -> dt.date | None:
    """글 화면의 '작성일 25-12-26 11:39'. 목록에 날짜가 없는 게시판이 있다."""
    m = _POSTED_IN_PAGE.search(text)
    if not m:
        return None
    y = int(m.group(1))
    try:
        return dt.date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def clean_title(title: str) -> str:
    """'applying 2027년 … 선발 안내 신청기간 2026-10-14 ~ …' 처럼 목록 칸이 같이 붙은 제목을 다듬는다."""
    title = re.sub(r"^[a-z]+\s+", "", title.strip())
    title = re.sub(r"^(?:공지|NOTICE|\d{1,6})\s+", "", title)  # 번호·공지 칸
    title = re.split(r"\s+(?:신청|접수|모집)기간\b|\s+(?:NEW|UPDATED|new)\b|\s+20\d\d[.\-/]\d\d?[.\-/]\d\d?\b", title)[0]
    return title.strip()


def wanted(title: str, loose: bool = False) -> bool:
    if not _WANT.search(title) or _SKIP.search(title):
        return False
    return loose or bool(_RECRUIT.search(title))


def attachments(page: str, base_url: str) -> list[tuple[str, str]]:
    """글 HTML → [(주소, 이름)]. 공고문처럼 보이는 이름을 앞에 둔다."""
    out: list[tuple[str, str]] = []
    for a in re.finditer(r"(?is)<a\b([^>]*)>(.*?)</a>", page):
        attrs, inner = a.group(1), a.group(2)
        m = re.search(r'href\s*=\s*"([^"]*)"', attrs) or re.search(r"href\s*=\s*'([^']*)'", attrs)
        if not m:
            continue
        href = _unescape_url(m.group(1))
        name = _text(inner)
        if not (_DOWNLOAD.search(href) or re.search(r"\.(hwp|hwpx|pdf|zip)\b", name, re.I)):
            continue
        if re.search(r"\.(jpe?g|png|gif)\b", href + " " + name, re.I):
            continue
        url = urllib.parse.urljoin(base_url, href)
        if all(url != u for u, _ in out):
            out.append((url, name))
    out.sort(key=lambda x: (not re.search(r"공고|요강|안내|모집", x[1]), bool(re.search(r"신청서|양식|서식|동의서", x[1]))))
    return out


_AMOUNT = re.compile(r"\d[\d,]*\s*만\s*원|생활비|생활\s*지원|학업\s*장려|등록금")


_LIVING_LINE = re.compile(r"생활비|생활\s*지원|생활\s*장학|학업\s*장려|생활안정")


def _excerpt(text: str) -> str:
    """지원 내용으로 보일 줄 몇 개 — 목록 요약과 '지원 용도'(생활비·등록금) 판정에 쓴다.
    금액이나 용도 낱말이 든 짧은 줄만 고르고(재단 소개 문단은 빼려고), 생활비를 말하는 줄을
    앞에 둔다 — 공고 앞부분의 '등록금 납부' 같은 줄 때문에 등록금 전용으로 잘못 보이지 않게."""
    living, other = [], []
    for ln in text.splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if not (4 <= len(ln) <= 90) or re.search(r"중지|환수|제외|불가", ln):
            continue
        if _LIVING_LINE.search(ln):
            living.append("○ " + ln)
        elif _AMOUNT.search(ln):
            other.append("○ " + ln)
    return "\n".join((living[:2] + other)[:3])


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(p.strip() for p in parts).encode("utf-8")).hexdigest()[:12]


def _org_from_title(title: str, default: str) -> str:
    m = re.match(r"\s*\[\s*([^\]]{2,40})\s*\]", title)
    if m and not re.search(r"공지|안내|알림|모집|장학", m.group(1)):
        return m.group(1).strip()
    return default


def read_post(f: Fetcher, post: dict[str, Any]) -> dict[str, Any]:
    """글을 열어 신청 기간을 읽는다. 본문 → 첨부 순서."""
    data, final_url, ctype = f.get(post["url"])
    page = decode_html(data, ctype)
    body = docs.html_text(page)
    # 게시일을 모르면 None 으로 둔다 — 오늘을 기준으로 연도를 고치면 지난 회차가 올해로 둔갑한다
    ref = post.get("posted") or posted_in_page(body)
    start, end = docs.find_period(body, ref)
    where, text = "본문", body
    if not (start and end):
        for url, name in attachments(page, final_url)[:MAX_FILES]:
            try:
                blob, _, _ = f.get(url, referer=final_url)
            except Exception:  # noqa: BLE001 - 첨부 하나 실패는 넘어간다
                continue
            ftext = docs.text_of(blob, name)
            s2, e2 = docs.find_period(ftext, ref)
            if s2 and e2:
                start, end, where, text = s2, e2, f"첨부 {name or '공고문'}", ftext
                break
            if e2 and not end:
                end, where, text = e2, f"첨부 {name or '공고문'}", ftext
    return {"start": start, "end": end, "where": where, "excerpt": _excerpt(text), "posted": ref}


def pick(board: dict[str, Any], posts: list[dict[str, Any]], today: dt.date) -> list[dict[str, Any]]:
    loose = bool(board.get("loose"))
    return [
        p for p in posts
        if wanted(p["title"], loose)
        and (p["posted"] is None and not loose or p["posted"] and (today - p["posted"]).days <= RECENT_DAYS)
    ][:MAX_POSTS]


def collect(boards: list[dict[str, Any]] | None = None, today: dt.date | None = None,
            fetcher: Fetcher | None = None, log=None,
            stats: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """게시판들을 돌며 최근 모집 공고를 장학금 항목 모양으로 돌려준다.
    stats 를 주면 게시판마다 {posts, picked, items, error} 를 채운다(화면에 보여 줄 것)."""
    today = today or dt.date.today()
    out: list[dict[str, Any]] = []
    for board in boards if boards is not None else BOARDS:
        f = fetcher or Fetcher()
        stat = {"posts": 0, "picked": 0, "items": 0, "error": ""}
        if stats is not None:
            stats[board["id"]] = stat
        try:
            data, final_url, ctype = f.get(board["url"])
            posts = list_posts(decode_html(data, ctype), final_url)
        except Exception as exc:  # noqa: BLE001
            stat["error"] = str(exc)[:200]
            if log:
                log.warning("게시판 %s 목록을 못 읽음: %s", board["id"], exc)
            continue
        picked = pick(board, posts, today)
        stat.update(posts=len(posts), picked=len(picked))
        for post in picked:
            try:
                got = read_post(f, post)
            except Exception as exc:  # noqa: BLE001
                if log:
                    log.warning("공고 %s 를 못 읽음: %s", post["url"], exc)
                continue
            posted = got["posted"]
            if posted and (today - posted).days > RECENT_DAYS:
                continue  # 목록엔 날짜가 없었지만 글을 열어 보니 오래된 글
            # 마감일을 못 읽었으면 시작일도 비운다 — 게시일을 시작일로 넣으면 '신청 가능' 처럼 보인다
            start = got["start"] or (posted if got["end"] else None)
            end = got["end"]
            if end and (today - end).days > CLOSED_KEEP_DAYS:
                continue  # 오래 지난 회차 ('최근 마감' 탭보다 오래된 것)
            if not end and (not posted or (today - posted).days > 60):
                continue  # 마감일을 못 읽은 오래된 글은 살아 있는지 알 수 없다
            title = clean_title(post["title"])
            org = _org_from_title(title, board["org"]) if board.get("bracket_org") else board["org"]
            name = title
            start_s = start.isoformat() if start else ""
            out.append({
                "id": _key(board["id"], post["url"]),
                "series": _key(org, name),
                "org": org,
                "name": name,
                "org_type": "",
                "product": "장학금",
                "category": "",
                "schools": [],
                "grades": [],
                "fields": [],
                "url": post["url"],
                "start": start_s,
                "end": end.isoformat() if end else "",
                "support": got["excerpt"],
                "source": board["label"],
                "source_id": board["id"],
                "school_board": bool(board.get("loose")),
                "notice_title": title,
                "posted": posted.isoformat() if posted else "",
                "period_from": got["where"],
            })
            stat["items"] += 1
    return out
