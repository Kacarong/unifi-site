"""장학금 추가 출처 테스트 — 공고문에서 날짜 읽기, 게시판·포털 파싱, 출처 합치기. 네트워크 없음.

    python tests/test_scholarship_sources.py

틀리면 조용히 망가지는 곳을 고정한다.
  - 신청 기간을 '결과 발표' 날짜와 헷갈리지 않는지, 연도가 빠지거나 틀린 날짜를 바로잡는지
  - 게시일을 모를 때 작년 공고를 올해 공고로 둔갑시키지 않는지
  - 본문에 날짜가 없으면 첨부 공고문(HWPX/ZIP)에서 읽는지
  - 같은 장학금이 CSV·포털·게시판에 겹쳐 있을 때 한 번만 보이는지
"""
from __future__ import annotations

import datetime as dt
import io
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("UNIFI_DATA_DIR", tempfile.mkdtemp(prefix="unifi-test-"))

from apps.scholarship import boards, docs, kosaf, logic  # noqa: E402

FAILURES: list[str] = []
D = dt.date.fromisoformat
TODAY = D("2026-11-03")


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: got {got!r}, want {want!r}")
        FAILURES.append(label)


def test_find_period() -> None:
    print("공고문에서 신청 기간 읽기")
    f = docs.find_period
    check("연-월-일 ~ 연-월-일", f("신청기간 ○ 2026-10-19 ~ 2026-11-13", D("2026-10-20")),
          (D("2026-10-19"), D("2026-11-13")))
    check("PDF 표에서 흩어진 요일·시각", f("1) 지원서 접수 : 2026년 10월 19일월(   ) 12시 ~ 11월 13일금(   ) 18시", D("2026-10-27")),
          (D("2026-10-19"), D("2026-11-13")))
    check("연도 없는 기간은 게시일 연도, 해를 넘기면 다음 해", f("모집기간: 12. 20.(금) ~ 1. 10.(금)", D("2026-12-18")),
          (D("2026-12-20"), D("2027-01-10")))
    check("연도 오타는 게시일 기준으로 바로잡음", f("신청기간: 2025.1.2~1.18", D("2026-01-02")),
          (D("2026-01-02"), D("2026-01-18")))
    check("게시일을 모르면 적힌 연도를 믿음(작년 공고를 올해로 옮기지 않음)",
          f("○ 접수 기간 : 2025.12.26 ~ 2026.01.09 18시", None), (D("2025-12-26"), D("2026-01-09")))
    check("'~날짜' 는 마감일만", f("지원 마감 기한 : ~2026.1.15", D("2025-11-17")), (None, D("2026-01-15")))
    check("'접수기한 날짜' 는 마감일만", f("접수기한 2026.10.11", D("2026-09-15")), (None, D("2026-10-11")))
    check("'까지' 는 마감일만", f("신청방법: 8월 11일(월)까지 학과장 추천", D("2026-07-16")), (None, D("2026-08-11")))
    check("결과 발표 날짜는 신청 기간이 아님",
          f("결과 발표: 12월 1일\n접수기간: 11월 3일 ~ 11월 20일", D("2026-11-01")), (D("2026-11-03"), D("2026-11-20")))
    check("표의 같은 행에서 라벨 앞 시작일", f("2026년 1월 2일(금)  ※ 온라인\n   지원서 접수\n  - 1월 13일(화) 17:00 마감", D("2025-12-01")),
          (D("2026-01-02"), D("2026-01-13")))
    check("날짜가 없으면 없음", f("장학생을 아래와 같이 선발합니다", TODAY), (None, None))


def _hwpx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        body = "".join(f"<hp:p><hp:run><hp:t>{ln}</hp:t></hp:run></hp:p>" for ln in text.splitlines())
        zf.writestr("Contents/section0.xml", f'<?xml version="1.0"?><hs:sec>{body}</hs:sec>')
    return buf.getvalue()


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_text_of() -> None:
    print("첨부 파일에서 글자 꺼내기")
    hwpx = _hwpx("1. 모집 개요\n접수기간: 2026. 11. 10.(화) ~ 11. 24.(화)")
    check("HWPX 형식 알아봄", docs.kind_of(hwpx), "hwpx")
    check("HWPX 본문 글자", "접수기간: 2026. 11. 10.(화) ~ 11. 24.(화)" in docs.text_of(hwpx), True)
    bundle = _zip({"apply_form.hwpx": _hwpx("신청서 작성일 2026. 1. 1."), "notice.hwpx": hwpx, "photo.jpg": b"\xff\xd8"})
    check("ZIP 안의 공고문까지 읽음", docs.find_period(docs.text_of(bundle), D("2026-11-03")),
          (D("2026-11-10"), D("2026-11-24")))
    check("이미지는 빈 글자", docs.text_of(b"\xff\xd8\xff\xe0 jpeg"), "")
    check("깨진 파일도 예외 없이 빈 글자", docs.text_of(b"\xd0\xcf\x11\xe0broken"), "")


LIST_PAGE = """
<ul class="menu"><li><a href="/about">재단소개 및 장학사업 안내</a></li></ul>
<table><tbody>
<tr><td>3</td><td class="tit"><a href="/not/default.asp?page=1&bidx=56512&sfield=2&gtxt=장학&gbn=10&amp;bgbn=R">[엔지니어링인재육성재단] 제2기 장학생 모집 안내</a></td><td class="date">2026.10.27</td></tr>
<tr><td>2</td><td class="tit"><a href="/not/default.asp?bidx=55000">2026 장학생 선발 결과 발표</a></td><td class="date">2026.10.20</td></tr>
<tr><td>1</td><td class="tit"><a href="/not/default.asp?bidx=40000">2025년도 장학생 모집 공고</a></td><td class="date">2025.03.02</td></tr>
</tbody></table>
"""

POST_PAGE = """
<div class="board_view"><p><img src="/upload/poster.jpg"></p>
<span>작성일 26-10-27 10:00</span>
<div class="view_file_box"><a href="/lib/file_down.asp?filename=notice.hwpx&furl=16">[공고문] 제2기 장학생 선발.hwpx</a>
<a href="/lib/file_down.asp?filename=form.hwpx&furl=16">신청서 양식.hwpx</a></div></div>
"""


class FakeFetcher:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url: str, referer: str = ""):
        self.asked.append(url)
        for key, data in self.pages.items():
            if key in url:
                return data, url, "text/html; charset=utf-8"
        raise OSError(f"없는 주소 {url}")


def test_boards() -> None:
    print("공고 게시판")
    posts = boards.list_posts(LIST_PAGE, "https://www.ksce.or.kr/not/default.asp?gbn=10")
    check("표의 행마다 글 하나 (메뉴 링크는 날짜가 없어도 글로 잡히지만 제목에서 걸러짐)",
          [p["title"] for p in posts if boards.wanted(p["title"])],
          ["[엔지니어링인재육성재단] 제2기 장학생 모집 안내", "2025년도 장학생 모집 공고"])
    check("주소의 '&gtxt=' 를 '>xt=' 로 망가뜨리지 않음", "&gtxt=장학&gbn=10&bgbn=R" in posts[1]["url"], True)
    check("목록의 날짜를 게시일로", posts[1]["posted"], D("2026-10-27"))
    check("결과 발표 글은 빼기", boards.wanted("2026 장학생 선발 결과 발표"), False)
    check("목록 칸이 붙은 제목 다듬기",
          boards.clean_title("applying 2027년 두산연강 대학 장학생 선발 안내 신청기간 2026-10-14 ~ 2026-11-13"),
          "2027년 두산연강 대학 장학생 선발 안내")
    check("목록 행 전체가 링크인 게시판의 제목 다듬기",
          boards.clean_title("공지 2027년도 한국지도자육성장학재단 일반장학생 신청 안내 UPDATED 학생과 2026-10-16 1,193"),
          "2027년도 한국지도자육성장학재단 일반장학생 신청 안내")
    check("글 화면의 작성일", boards.posted_in_page("작성일 25-12-26 11:39"), D("2025-12-26"))
    files = boards.attachments(POST_PAGE, "https://www.ksce.or.kr/not/default.asp")
    check("첨부는 공고문을 먼저, 신청서 양식은 뒤로", [n for _, n in files],
          ["[공고문] 제2기 장학생 선발.hwpx", "신청서 양식.hwpx"])

    fetcher = FakeFetcher({  # 앞에서부터 맞춰 본다 — 글 주소에도 'gbn=10' 이 들어 있어 목록은 맨 뒤
        "notice.hwpx": _hwpx("○ 장학금: 학기당 생활지원금 300만원 지급\n지원서 접수 : 2026년 10월 19일 ~ 11월 13일"),
        "bidx=56512": POST_PAGE.encode(),
        "bidx=40000": "<p>작성일 2025-03-02</p><p>접수기간 2025.3.2 ~ 2025.3.20</p>".encode(),
        "gbn=10": LIST_PAGE.encode(),
    })
    board = {"id": "ksce_news", "label": "대한토목학회 토목계소식", "org": "대한토목학회", "bracket_org": True,
             "url": "https://www.ksce.or.kr/not/default.asp?gbn=10"}
    got = boards.collect([board], today=TODAY, fetcher=fetcher)
    check("최근 모집 글 하나만", [(g["org"], g["start"], g["end"]) for g in got],
          [("엔지니어링인재육성재단", "2026-10-19", "2026-11-13")])
    check("일정을 어디서 읽었는지 남김", got[0]["period_from"], "첨부 [공고문] 제2기 장학생 선발.hwpx")
    check("지원 내용 줄을 뽑아 생활비 판정에 씀", logic.purpose(got[0]), "living")
    check("오래된 글은 열어 보지도 않음", any("bidx=40000" in u for u in fetcher.asked), False)

    school = {"id": "school", "loose": True}
    school_posts = [
        {"title": "2026학년도 부경 더채움 장학금", "posted": D("2026-10-11"), "url": "a"},
        {"title": "2026-2학기 국가장학금Ⅰ유형 장학금 지급 안내(2차)", "posted": D("2026-10-26"), "url": "b"},
        {"title": "「부경 더채움 장학금」서식 변경사항 안내", "posted": D("2026-10-07"), "url": "c"},
        {"title": "맞춤형 장학검색", "posted": None, "url": "d"},  # 메뉴 링크
    ]
    check("학교 게시판은 '모집' 낱말 없어도 받되, 지급·서식 안내와 날짜 없는 메뉴는 뺌",
          [p["url"] for p in boards.pick(school, school_posts, TODAY)], ["a"])
    stats: dict = {}
    boards.collect([{**board, "id": "bad", "url": "http://127.0.0.1:8090/"}], today=TODAY, stats=stats)
    check("내부망 주소는 받지 않고 실패 원인을 남김", stats["bad"]["error"], "내부망 주소는 넣을 수 없습니다")


DETAIL_PAGE = """
<div id="content_wrap" class="width_1200 portal"><div>
<h4 class="bg_title"><span>꿈 Dream 장학금</span></h4>
<table><tbody>
<tr><th>상품구분</th><th>장학금</th><th>운영기관구분</th><th>기타</th><th>운영기관명</th><th>사랑의달팽이</th></tr>
<tr><td>홈페이지주소</td><td colspan="3"><a href="https://www.soree119.com/">https://www.soree119.com/</a></td></tr>
<tr><td>대학구분</td><td><ul><li>4년제(5~6년제포함)</li><li>제한없음</li></ul></td></tr>
<tr><td>학년구분</td><td><ul><li>대학신입생</li><li>대학2학기</li></ul></td></tr>
<tr><td>학과구분</td><td><ul><li>제한없음</li></ul></td></tr>
<tr><td>지원금액</td><td>○ 학습 장학금 200만원 지원</td></tr>
<tr><td>지역거주구분</td><td>해당없음</td></tr>
<tr><td>신청기간</td><td>○ 2026-10-19 ~ 2026-11-13</td></tr>
</tbody></table></div></div>
"""


def _list_row(code: str, org: str, name: str, end: str) -> str:
    return (f'<tr><td class="hide_m">1</td><td class="hide_m">{org}</td><td>{name}</td><td>기타</td>'
            f'<td>장학금</td><td>○ 02-000-0000</td><td class="hide_m">{end}</td>'
            f"<td><a href=\"javascript:fn_goDtl('{code}');\">상세보기</a></td></tr>")


def test_kosaf() -> None:
    print("한국장학재단 실시간 포털")
    rows = kosaf.parse_list("<table><tbody>" + _list_row("2704367001", "사랑의달팽이", "꿈 Dream 장학금", "2026-11-13")
                            + "</tbody></table>")
    check("목록 행", rows, [{"code": "2704367001", "org": "사랑의달팽이", "name": "꿈 Dream 장학금", "end": "2026-11-13"}])
    item = kosaf.to_item(kosaf.parse_detail(DETAIL_PAGE))
    check("상세 → CSV 와 같은 모양", (item["org"], item["name"], item["start"], item["end"], item["grades"]),
          ("사랑의달팽이", "꿈 Dream 장학금", "2026-10-19", "2026-11-13", ["대학신입생", "대학2학기"]))
    check("CSV 에 같은 장학금이 오면 같은 id(알림 두 번 안 감)", item["id"],
          logic_id("사랑의달팽이", "꿈 Dream 장학금", "2026-10-19"))

    pages = {
        1: [{"code": "1", "org": "새재단", "name": "새 장학금", "end": "2026-11-20"},
            {"code": "2", "org": "옛재단", "name": "옛 장학금", "end": "2026-10-30"}],
        2: [{"code": "2", "org": "옛재단", "name": "옛 장학금", "end": "2026-10-30"}],
        3: [{"code": "3", "org": "옛재단2", "name": "장학금", "end": "2026-10-01"}],
        4: [{"code": "9", "org": "안읽음", "name": "장학금", "end": "2026-12-01"}],
    }
    asked: list[str] = []

    def detail(code: str) -> dict[str, str]:
        asked.append(code)
        return {"운영기관명": "새재단", "상품명": "새 장학금", "모집시작일": "2026-11-01", "모집종료일": "2026-11-20"}

    known = {("옛재단", "옛 장학금", "2026-10-30"), ("옛재단2", "장학금", "2026-10-01")}
    cache: dict = {}
    got = kosaf.collect(known, cache, TODAY, list_page=lambda no: pages.get(no, []), detail=detail)
    check("CSV 에 없는 것만", [g["name"] for g in got], ["새 장학금"])
    check("CSV 에 다 있는 쪽이 두 번 이어지면 멈춤", asked, ["1"])
    kosaf.collect(known, cache, TODAY, list_page=lambda no: pages.get(no, []), detail=detail)
    check("받아 둔 상세는 다시 받지 않음", asked, ["1"])


def logic_id(org: str, name: str, start: str) -> str:
    from apps.scholarship import source

    return source._key(org, name, start)


def item(org, name, start, end, **kw):
    from apps.scholarship import source

    return {"id": source._key(org, name, start), "series": source._key(org, name), "org": org, "name": name,
            "start": start, "end": end, **kw}


def test_merge() -> None:
    print("출처 합치기")
    base = [item("(재)두산연강재단", "장학생", "2025-10-15", "2025-11-14"),
            item("(재)엔지니어링인재육성재단", "장학생", "2026-10-19", "2026-11-13"),
            item("재단A", "장학금", "2026-10-01", "2026-10-31")]
    notice = {**item("두산연강재단", "2027년 두산연강 대학 장학생 선발 안내", "2026-10-14", "2026-11-13"),
              "notice_title": "2027년 두산연강 대학 장학생 선발 안내", "source": "두산연강재단"}
    same_notice = {**item("엔지니어링인재육성재단", "[엔지니어링인재육성재단] 제2기 장학생 모집 안내", "2026-10-19", "2026-11-13"),
                   "notice_title": "[엔지니어링인재육성재단] 제2기 장학생 모집 안내", "source": "대한토목학회 토목계소식",
                   "period_from": "첨부 공고문.pdf", "url": "https://www.ksce.or.kr/not/default.asp?bidx=56512"}
    portal_dup = {**item("재단A", "장학금", "2026-10-01", "2026-10-31"), "source": "한국장학재단 포털"}
    portal_new = {**item("재단B", "장학금", "2026-11-01", "2026-11-30"), "source": "한국장학재단 포털"}
    out = logic.merge(base, [notice, same_notice, portal_dup, portal_new])
    check("CSV 에 이미 있는 포털 항목은 빼고, 새것만 더함", len(out), 5)
    doosan = [x for x in out if x.get("notice_title", "").startswith("2027년 두산")]
    check("기관의 장학금이 하나면 게시판 공고를 그 장학금의 새 회차로", doosan[0]["series"], base[0]["series"])
    eng = [x for x in out if logic.org_core(x["org"]) == "엔지니어링인재육성재단"]
    check("같은 기관·같은 마감이면 한 번만, 원래 항목에 원문 주소를 붙임",
          (len(eng), eng[0].get("notice_url"), eng[0].get("period_from")), (1, same_notice["url"], "첨부 공고문.pdf"))
    school_repost = {**item("부경대학교", "2026년 부산지역인재 장학금 하반기 생활장학금 지원 신청 공고", "2026-10-14", "2026-10-28"),
                     "notice_title": "2026년 부산지역인재 장학금 하반기 생활장학금 지원 신청 공고<~10. 28.>",
                     "url": "https://www.pknu.ac.kr/main/163?action=view&no=1", "source": "부경대 등록·장학 공지"}
    busan = item("부산광역시청", "부산지역인재 장학금", "2026-10-14", "2026-10-28")
    out2 = logic.merge([busan], [school_repost])
    check("학교가 다시 올린 외부 공고는 원래 장학금에 원문 링크로만 붙음",
          (len(out2), out2[0].get("notice_url")), (1, school_repost["url"]))
    check("두산 새 회차 덕분에 '작년 일정 참고' 에서 빠짐",
          [f["org"] for f in logic.forecast(out, D("2026-10-01"))], [])


def test_review_regressions() -> None:
    print("학교 게시판 공고끼리 합치지 않기 · 못 본 공고 남기기 · 일정 미확인")
    from apps.scholarship import worker

    def notice(title, start, end, sid="pknu_civil", school=True, posted="2026-10-01"):
        it = item("부경대학교 토목공학과", title, start, end)
        return {**it, "notice_title": title, "url": f"https://civil.pknu.ac.kr/{it['id']}", "posted": posted,
                "source": "부경대 토목공학과", "source_id": sid, "school_board": school}

    a = notice("2026학년도 부경 더채움 장학금", "2026-09-01", "2026-12-31")
    b = notice("푸른등대 기부장학금 선발 안내", "2026-10-22", "2026-12-31")
    csv_school = item("부경대학교 토목공학과", "동문회 장학금", "2026-09-01", "2026-12-31")
    out = logic.merge([csv_school], [a, b])
    check("같은 학교·같은 마감이어도 서로 다른 장학금은 따로", sorted(x.get("notice_title", x["name"]) for x in out),
          ["2026학년도 부경 더채움 장학금", "동문회 장학금", "푸른등대 기부장학금 선발 안내"])
    check("학교 공고를 학교의 다른 장학금 회차로 묶지 않음", {x["series"] for x in out if x.get("notice_title")},
          {a["series"], b["series"]})

    old = notice("정효택 장학생 선발 계획", "2026-10-14", "2026-10-19")
    too_old = notice("작년 장학생 선발", "2026-02-01", "2026-03-01")
    off = notice("끈 게시판 공고", "2026-10-01", "2026-11-20", sid="wooyang")
    legacy = {k: v for k, v in notice("예전 자료(출처 id 없음)", "2026-10-01", "2026-11-20").items() if k != "source_id"}
    kept = worker.keep_previous([old, too_old, off, legacy], [a], TODAY,
                                lambda it: (it.get("source_id") or "pknu_civil") == "pknu_civil")
    check("이번에 못 본 공고도 남기고, 오래된 것·끈 게시판 것만 뺌",
          [x["notice_title"] for x in kept], ["2026학년도 부경 더채움 장학금", "정효택 장학생 선발 계획", "예전 자료(출처 id 없음)"])
    check("게시판을 못 읽은 회차(빈 결과)에도 이전 공고는 그대로",
          len(worker.keep_previous([a, b], [], TODAY)), 2)

    fetcher = FakeFetcher({
        "no=1": '<p>작성일 2026-10-30</p><p><img src="/poster.jpg"></p>'.encode(),
        "list": '<table><tr><td><a href="/b?no=1">2026 부경 장학생 선발 안내</a></td><td>2026-10-30</td></tr></table>'.encode(),
    })
    got = boards.collect([{"id": "pknu_civil", "label": "부경대 토목공학과", "org": "부경대학교 토목공학과",
                           "url": "https://civil.pknu.ac.kr/list", "loose": True}], today=TODAY, fetcher=fetcher)
    check("이미지뿐인 공고는 시작·마감을 비워 둠", [(g["start"], g["end"], g["posted"]) for g in got],
          [("", "", "2026-10-30")])
    check("마감을 모르면 '일정 미확인'", logic.status(got[0], TODAY), "unknown")
    notes = logic.plan_notifications(got, profile={}, settings={"notify_new": True, "reminder_days": [7]},
                                     stars=[got[0]["series"]], known_ids=set(), sent=set(), today=TODAY)
    check("일정 미확인 공고는 새 장학금·관심 알림 모두 안 보냄", notes, [])


def main() -> int:
    test_find_period()
    test_text_of()
    test_boards()
    test_kosaf()
    test_merge()
    test_review_regressions()
    if FAILURES:
        print(f"\n실패 {len(FAILURES)}건")
        return 1
    print("\n모두 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
