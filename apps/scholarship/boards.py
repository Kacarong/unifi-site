"""공고 게시판 — 대한토목학회·재단·부경대·부산 구·군 장학회 홈페이지에 올라온 장학생 모집 글.

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

from . import docs, dreamspon

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
    {
        "id": "pknu_civil_notice",
        "label": "부경대 토목공학과 공지",
        "org": "부경대학교 토목공학과",
        "url": "https://civil.pknu.ac.kr/civil/5345?pageIndex=1&bbsId=2402699&searchCondition=title&searchKeyword=%EC%9E%A5%ED%95%99",
        "loose": True,
    },
    {
        "id": "pknu_coe",
        "label": "부경대 공과대학 공지",
        "org": "부경대학교 공과대학",
        "url": "https://coe.pknu.ac.kr/?mode=1&menucode=0406010000&kind=title&keyword=%EC%9E%A5%ED%95%99",
        "loose": True,
    },
    {
        "id": "kosffl",
        "label": "한국지도자육성장학재단",
        "org": "(재)한국지도자육성장학재단",
        "url": "https://www.kosffl.or.kr/news/notice",
    },
    {
        "id": "kfas",
        "label": "한국고등교육재단",
        "org": "(재)한국고등교육재단",
        # https 는 인증서 체인이 덜 갖춰져 있어 열리지 않는다
        "url": "http://www.kfas.or.kr/bbs/board.php?bo_table=kfas_2028_ntc_latest&sca=%EA%B3%B5%EC%A7%80%EC%82%AC%ED%95%AD",
        "want": r"장학|지원자\s*모집",  # '인재림(人材林) 제7기 지원자 모집'
    },
    {
        "id": "asan",
        "label": "아산사회복지재단",
        "org": "아산사회복지재단",
        "url": "https://www.asanfoundation.or.kr/af/foundation/notice/afFoundationNoticeList.do?noticeTypeClsf=N",
        # 모든 행의 href 가 같고 글 번호는 onclick="fnDetail(11306)" 에만 있다
        "link": [r"fnDetail\((\d+)\)",
                 "https://www.asanfoundation.or.kr/af/foundation/notice/afFoundationNoticeDetail.do?idx={}&noticeTypeClsf=N"],
    },
    {
        "id": "postf",
        "label": "포스코청암재단",
        "org": "포스코청암재단",
        "url": "https://www.postf.org/news/notice",
    },
    # 부산 구·군 장학회 — 그 구·군에 사는(보호자가 사는) 학생만 뽑는다. region 으로 지역을 붙인다.
    {
        "id": "suyeong",
        "label": "수영구장학재단",
        "org": "재단법인 수영구장학재단",
        "region": "부산광역시 수영구",
        "url": "https://www.suyeong.go.kr/janghak/board/list.suyeong?boardId=BBS_0000140&menuCd=DOM_000002802001000000&contentsSid=2261",
    },
    {
        "id": "namgu",
        "label": "부산 남구장학회",
        "org": "(재)부산광역시 남구장학회",
        "region": "부산광역시 남구",
        "url": "https://www.bsnamgu.go.kr/board/list.namgu?boardId=BBS_0000128&menuCd=DOM_000000102010009000&contentsSid=1229",
    },
    {
        "id": "bukgu",
        "label": "부산 북구청 새소식",
        "org": "(재)부산북구장학회",
        "region": "부산광역시 북구",
        "url": "https://www.bsbukgu.go.kr/board/list.bsbukgu?boardId=BBS_0000023&menuCd=DOM_000000105001001000&contentsSid=368&searchType=DATA_TITLE&keyword=%EC%9E%A5%ED%95%99",
        "loose": True,
    },
    {
        "id": "gijang",
        "label": "기장군 알림사항",
        "org": "부산광역시 기장군",
        "region": "부산광역시 기장군",
        "url": "https://www.gijang.go.kr/board/list.gijang?boardId=BBS_0000002&menuCd=DOM_000000101001001000&contentsSid=44&searchType=DATA_TITLE&searchOperation=OR&keyword=%EC%9E%A5%ED%95%99",
        "loose": True,
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
    r"|지급|납부|분할|서식|양식|변경사항|반환|환수|정정|연장 안내|만족도|설문|소감문|연수\s*교육|면접\s*(?:심사|일정)"
)

_DATE_IN_ROW = re.compile(r"(20\d\d)\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})")
# 구청 게시판은 연도를 두 자리로 적는다('26.09.18'). 네 자리 날짜가 없을 때만 본다.
_SHORT_DATE_IN_ROW = re.compile(r"(?<![\d.\-])([12]\d)\s*[.\-]\s*(\d\d)\s*[.\-]\s*(\d\d)(?![\d.\-])")
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


def _row_date(text: str) -> dt.date | None:
    for pat, base in ((_DATE_IN_ROW, 0), (_SHORT_DATE_IN_ROW, 2000)):
        m = pat.search(text)
        if m:
            try:
                return dt.date(base + int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def list_posts(page: str, base_url: str, link: tuple[str, str] | list[str] | None = None) -> list[dict[str, Any]]:
    """목록 HTML → [{title, url, posted}]. 같은 주소는 한 번만.
    link: 글 주소가 onclick 에만 있는 게시판용 (정규식, 주소 틀) — onclick 의 'fnDetail(11306)' 번호를
    '…Detail.do?idx={}' 에 넣는다. 맞으면 href 보다 먼저 쓴다(href 는 모든 행이 같은 주소다)."""
    page = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    chunks = re.findall(r"(?is)<tr[\s>].*?</tr>|<li[\s>].*?</li>|<article[\s>].*?</article>", page)
    seen: set[str] = set()
    out = []
    for chunk in chunks:
        if len(chunk) > 6000:  # 메뉴 전체를 감싼 바깥 <li>
            continue
        best = None
        for a in re.finditer(r"(?is)<a\b([^>]*)>(.*?)</a>", chunk):
            attrs, inner = a.group(1), a.group(2)
            title = _text(inner) or _text(re.search(r'title="([^"]*)"', attrs).group(1) if 'title="' in attrs else "")
            if len(title) < 6:
                continue
            href = ""
            lm = re.search(link[0], attrs) if link else None
            if lm:
                href = link[1].format(*lm.groups())
            m = None if href else re.search(r'href\s*=\s*"([^"]*)"', attrs) or re.search(r"href\s*=\s*'([^']*)'", attrs)
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
        out.append({"title": best[0], "url": url, "posted": _row_date(_text(chunk))})
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
    title = re.split(r"\s+(?:신청|접수|모집)기간\b|\s+(?:NEW|UPDATED|new)\b|\s+20\d\d[.\-/]\d\d?[.\-/]\d\d?\b"
                     r"|\s+(?:[HN]\s+)?인기글(?![가-힣])", title)[0]  # 그누보드 '… H 인기글 (본문 미리보기)'
    twice = re.fullmatch(r"(.{6,}?)\s+\1", title.strip())  # 같은 제목을 두 칸에 적은 목록
    return (twice.group(1) if twice else title).strip()


def wanted(title: str, loose: bool = False, want: str = "") -> bool:
    """want: 장학 재단처럼 제목에 '장학' 이 없는 모집 글('인재림 제7기 지원자 모집')을 올리는 게시판의 주제 낱말."""
    if not re.search(want or _WANT.pattern, title) or _SKIP.search(title):
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
        if href.lower().startswith("javascript"):
            # javascript:file_download('/download?db=1&id=5350&no=0', '공고문.pdf') — 안의 주소를 쓴다
            js = re.search(r"""['"]((?:/|https?://)[^'"]+)['"]""", href)
            if not js:
                continue
            href = js.group(1)
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


_AMOUNT = re.compile(r"\d[\d,]*\s*만\s*원|\d{1,3}(?:,\d{3})+\s*원|생활비|생활\s*지원|학업\s*장려|등록금")


_LIVING_LINE = re.compile(r"생활비|생활\s*지원|생활\s*장학|학업\s*장려|생활안정")


def _excerpt(text: str) -> str:
    """지원 내용으로 보일 줄 몇 개 — 목록 요약과 '지원 용도'(생활비·등록금) 판정에 쓴다.
    금액이나 용도 낱말이 든 짧은 줄만 고르고(재단 소개 문단은 빼려고), 생활비를 말하는 줄을
    앞에 둔다 — 공고 앞부분의 '등록금 납부' 같은 줄 때문에 등록금 전용으로 잘못 보이지 않게."""
    living, other = [], []
    for ln in text.splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if not (4 <= len(ln) <= 90) or re.search(r"중지|환수|제외|불가", ln) or _SECTION_JUNK.search(ln):
            continue
        if _LIVING_LINE.search(ln):
            living.append("○ " + ln)
        elif _AMOUNT.search(ln):
            other.append("○ " + ln)
    return "\n".join((living[:2] + other)[:3])


# ---------------------------------------------------------------------------
# 공고 상세 — 지원 자격·선발 인원·선발 방법·제출 서류·신청 방법
#
# 공고문은 '1. 선발 인원 : 총 90명', '□ 지원자격', '가. 제출서류' 처럼 항목 제목을 줄 앞에
# 두고 그 아래에 내용을 적는다. 제목 줄을 찾아 다음 제목이 나올 때까지(최대 8줄) 모은다.
# 한국장학재단 자료의 같은 칸(special·quota·selection·documents)에 넣어 화면이 똑같이 보인다.
# ---------------------------------------------------------------------------
_SECTION_LABELS = {
    "special": r"(?:지원|신청|응모|선발|추천|장학생)\s*자격|(?:지원|선발|신청|모집|장학)\s*대상(?:자)?|자격\s*(?:요건|기준|조건)",
    "quota": r"선발\s*(?:인원|규모|예정\s*인원)|모집\s*인원|지원\s*규모",
    "selection": r"선발\s*(?:방법|절차|기준)|심사\s*(?:방법|기준|절차)|전형\s*(?:방법|절차)",
    "documents": r"제출\s*서류|구비\s*서류|신청\s*서류",
    "how": r"신청\s*방법|접수\s*방법|신청\s*경로|제출\s*방법|신청\s*절차",
}
# 줄 앞 번호·기호만 — '가.' '나)' 처럼 뒤에 점·괄호가 붙은 글자 하나만 번호로 본다.
# (글자 범위 [가-하] 를 그대로 쓰면 '필수 제출 서류 누락' 의 '필수' 까지 번호로 먹어 제목이 된다)
_BULLET = r"(?:[\s\d.)(\[\]Ⅰ-Ⅹ□■▢○◎●◦▶▷◆◇※\-–·•❍◈◾➊-➓①-⑳]|[가-힣](?=\s*[.)])|[ㅇㅁ](?=\s))*"
_SECTION_HEAD = re.compile(
    "^" + _BULLET + r"(?:장학금\s*|장학생\s*)?(?:"
    + "|".join(f"(?P<{k}>{v})" for k, v in _SECTION_LABELS.items())
    + r")\s*(?:\([^)]{0,20}\))?\s*(?P<rest>[:：].*|\s.{0,80}|)$"
)
# 두 항목을 한 제목에 묶은 줄('지원자격 및 제출서류', '지원자격, 심사방법 등은 붙임 참조')
_JOINED_HEAD = re.compile(r"^(?:및|,|·|/|등)")
_SECTION_STOP = re.compile(r"^(?:이전\s*글|다음\s*글|목록\s*보기|목록|첨부\s*파일)(?![가-힣])|^(?:이전|다음)$")
_SECTION_JUNK = re.compile(r"\.(?:hwpx?|pdf|zip|docx?|jpe?g|png)\b|·{4,}|\.{6,}|^\[?붙임", re.I)
SECTION_LINES = 8
SECTION_CHARS = 500

# 줄 앞 번호의 종류와 깊이. '1.' 아래에 '가.', 그 아래에 '1)', '가)' 를 쓰는 공문 관례를 따른다.
_MARKS = [
    ("roman", 0, re.compile(r"\s*([Ⅰ-Ⅹ])")),
    ("num.", 1, re.compile(r"\s*(\d{1,2})\s*\.(?!\d)")),
    ("box", 1, re.compile(r"\s*[□■]")),
    ("kor.", 2, re.compile(r"\s*([가-하])\s*\.")),
    ("num)", 3, re.compile(r"\s*\(?(\d{1,2})\)")),
    ("kor)", 3, re.compile(r"\s*\(?([가-하])\)")),
]


def _mark(line: str) -> tuple[str, int, int | None] | None:
    """(종류, 깊이, 번호) — 번호가 없는 표시(□)는 None."""
    for kind, level, pat in _MARKS:
        m = pat.match(line)
        if m:
            g = m.group(1) if m.groups() else None
            n = int(g) if g and g.isdigit() else (ord(g) if g else None)
            return kind, level, n
    return None


def details(text: str) -> dict[str, str]:
    """공고 글자 → {special, quota, selection, documents, how} 중 찾은 것만.
    제목 줄 다음부터 다음 항목 제목, 또는 제목과 같거나 얕은 번호 줄('3.') 앞까지 모은다.
    내용이 '1. … 2. …' 처럼 제목과 같은 깊이의 번호 목록이면 번호가 이어지는 동안은 계속 모은다."""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln and not _SECTION_JUNK.search(ln)]
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = _SECTION_HEAD.match(lines[i]) if len(lines[i]) <= 120 else None
        if not m:
            i += 1
            continue
        key = next(k for k in _SECTION_LABELS if m.group(k))
        rest = re.sub(r"^[:：]\s*", "", m.group("rest").strip())
        if _JOINED_HEAD.match(rest):
            rest = ""
        body = [rest] if rest else []
        head = _mark(lines[i])
        level = head[1] if head else 2
        run: tuple[str, int | None] | None = None  # 내용이 번호 목록일 때 (종류, 마지막 번호)
        j = i + 1
        while j < len(lines) and len(body) < SECTION_LINES:
            ln = lines[j]
            if _SECTION_STOP.match(ln) or _SECTION_HEAD.match(ln):
                break
            mk = _mark(ln)
            if mk and mk[1] <= level:
                listed = (not body and mk[2] == 1 and mk[0] != "roman") or (
                    run and run[0] == mk[0] and run[1] is not None and mk[2] == run[1] + 1)
                if not listed:
                    break
                run = (mk[0], mk[2])
            body.append(ln)
            j += 1
        got = "\n".join(body).strip()
        if len(re.findall(r"[가-힣0-9]", got)) >= 2 and key not in out:
            if len(got) > SECTION_CHARS:
                got = got[:SECTION_CHARS].rsplit("\n", 1)[0] + "\n…"
            out[key] = got
        i = j
    return out


_CONTENT_END = re.compile(r"^(?:이전\s*글|다음\s*글|목록\s*보기)(?![가-힣])")


def content_of(body: str, title: str) -> str:
    """글 화면 글자에서 메뉴·이전글/다음글을 덜어 낸 본문 — 글 제목 줄부터 '이전글/다음글' 앞까지.
    메뉴의 '등록금안내' 같은 줄이 지원 내용 요약에 섞이지 않게 한다. 제목 줄은 제목만 적힌 짧은
    줄이다(본문 문장 속 제목은 아니다). 여러 번 나오면(쪽 제목, 경로, 글 제목) 뒤의 것부터 보되,
    이전글/다음글 바로 뒤의 제목(같은 이름의 지난 회차)과 본문이 거의 없는 곳은 건너뛴다."""
    head = re.sub(r"\s+", " ", clean_title(title))[:15]
    lines = body.splitlines()
    flat = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
    if len(head) >= 6:
        limit = len(clean_title(title)) + 30
        hits = [i for i, ln in enumerate(flat) if head in ln and len(ln) <= limit
                and not any(_CONTENT_END.match(x) for x in flat[max(0, i - 2):i])]
        for start in reversed(hits):
            end = next((i for i in range(start + 1, len(flat)) if _CONTENT_END.match(flat[i])), len(flat))
            part = "\n".join(lines[start:end])
            if len(re.findall(r"[가-힣]", part)) >= 80:
                return part
    return body


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(p.strip() for p in parts).encode("utf-8")).hexdigest()[:12]


def _org_from_title(title: str, default: str) -> str:
    m = re.match(r"\s*\[\s*([^\]]{2,40})\s*\]", title)
    if m and not re.search(r"공지|안내|알림|모집|장학", m.group(1)):
        return m.group(1).strip()
    return default


def read_post(f: Fetcher, post: dict[str, Any]) -> dict[str, Any]:
    """글을 열어 신청 기간과 상세(자격·인원·서류…)를 읽는다. 본문 → 첨부 순서."""
    data, final_url, ctype = f.get(post["url"])
    page = decode_html(data, ctype)
    body = docs.html_text(page)
    content = content_of(body, post.get("title", ""))
    # 게시일을 모르면 None 으로 둔다 — 오늘을 기준으로 연도를 고치면 지난 회차가 올해로 둔갑한다
    ref = post.get("posted") or posted_in_page(body)
    start, end = docs.find_period(body, ref)
    where = "본문"
    texts = [content]  # 지원 내용 요약·상세를 뽑을 글자 — 본문, 그리고 읽은 공고문
    files = attachments(page, final_url)[:MAX_FILES]
    opened = 0
    detail_only: list[str] = []  # 날짜는 없었지만 연 공고문 — 상세 칸에만 쓴다
    if not (start and end):
        for url, name in files:
            try:
                blob, _, _ = f.get(url, referer=final_url)
            except Exception:  # noqa: BLE001 - 첨부 하나 실패는 넘어간다
                continue
            opened += 1
            ftext = docs.text_of(blob, name)
            s2, e2 = docs.find_period(ftext, ref)
            if s2 and e2:
                start, end, where = s2, e2, f"첨부 {name or '공고문'}"
                texts.append(ftext)
                break
            if e2 and not end:
                end, where = e2, f"첨부 {name or '공고문'}"
                texts.append(ftext)
            else:
                detail_only.append(ftext)
    info = details(content)
    for t in texts[1:] + detail_only:
        info = {**details(t), **info}  # 본문에 적힌 것을 먼저, 빈 칸만 공고문에서
    if len(info) < 3 and files and not opened:
        # 본문에 날짜만 있고 자세한 것은 공고문에 있는 글이 많다 — 첫 공고문 하나만 더 읽는다
        url, name = files[0]
        try:
            blob, _, _ = f.get(url, referer=final_url)
            # 상세 칸만 채운다. 지원 내용 요약(생활비 판정)에는 넣지 않는다 — 업무처리기준 같은
            # 긴 문서의 '생활비 대출', '생활비 … 인정' 줄이 생활비 장학금으로 잘못 읽힌다.
            info = {**details(docs.text_of(blob, name)), **info}
        except Exception:  # noqa: BLE001
            pass
    return {"start": start, "end": end, "where": where, "excerpt": _excerpt("\n".join(texts)),
            "posted": ref, "details": info}


# 학적 — 공고 제목·자격 칸에 적힌 대상. 학교·구청 게시판에는 중·고등학생 공고와 대학원 공고가 섞인다.
_SCHOOL_KID = re.compile(r"초등|중학|고등학|고교")
_COLLEGE = re.compile(r"대학|학부|전문대")
_GRAD = re.compile(r"대학원|석사|박사")
_UNDERGRAD = re.compile(r"대학생|학부|대학\s*장학생|대학교")


def for_college(item: dict[str, Any]) -> bool:
    """대학생·대학원생이 받을 수 있는 공고인가. '중학교 2학년 재학생' 처럼 초·중·고만 적고
    대학을 한 번도 말하지 않는 공고만 아니라고 본다."""
    target = f"{item.get('notice_title') or item.get('name', '')}\n{item.get('special', '')}"
    return not (_SCHOOL_KID.search(target) and not _COLLEGE.search(target))


def grades_of(title: str) -> list[str]:
    """제목이 대학원만 말하면 대학원 과정으로(학부 재학생의 '내 조건' 에서 빠지게). 그 밖에는 모름([])."""
    return list(dreamspon.GRAD_ONLY) if _GRAD.search(title) and not _UNDERGRAD.search(title) else []


def pick(board: dict[str, Any], posts: list[dict[str, Any]], today: dt.date) -> list[dict[str, Any]]:
    loose = bool(board.get("loose"))
    return [
        p for p in posts
        if wanted(clean_title(p["title"]), loose, board.get("want", ""))
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
            posts = list_posts(decode_html(data, ctype), final_url, board.get("link"))
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
                # 구·군 장학회 게시판은 그 지역 주민 자녀만 뽑는다 — 지역 판정(logic.place)에 쓴다
                "category": "지역연고" if board.get("region") else "",
                "region": board.get("region", ""),
                "schools": [],
                "grades": grades_of(title),
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
                **got["details"],
            })
            if not for_college(out[-1]):
                out.pop()  # 초·중·고 전용 공고
                continue
            stat["items"] += 1
    return out
