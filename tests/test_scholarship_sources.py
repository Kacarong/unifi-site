"""장학금 추가 출처 테스트 — 공고문에서 날짜 읽기, 게시판·포털 파싱, 출처 합치기. 네트워크 없음.

    python tests/test_scholarship_sources.py

틀리면 조용히 망가지는 곳을 고정한다.
  - 신청 기간을 '결과 발표' 날짜와 헷갈리지 않는지, 연도가 빠지거나 틀린 날짜를 바로잡는지
  - 게시일을 모를 때 작년 공고를 올해 공고로 둔갑시키지 않는지
  - 본문에 날짜가 없으면 첨부 공고문(HWPX/ZIP)에서 읽는지
  - 같은 장학금이 CSV·포털·게시판·드림스폰에 겹쳐 있을 때 한 번만 보이는지
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

from apps.scholarship import boards, docs, dreamspon, kosaf, logic  # noqa: E402

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
    check("'신청과 관련하여' 처럼 모집 낱말 없이 신청 기간을 알리는 글도 받기",
          boards.wanted("제30기 (2026년 하반기) 대학생 장학금 신청과 관련하여"), True)
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


def _ds_row(idx: str, name: str, org: str, tags: list[str]) -> str:
    spans = "".join(f"<span>#{t}</span>" for t in tags)
    return (f'<tr class=""><td class="td_subject"><p class="title"><a href="/scholarship/view.html?idx={idx}">{name}</a></p>'
            f'<div class="hashtag">{spans}</div></td><td>{org}</td><td class="td_day">D-2</td><td class="hit">1</td></tr>')


DS_DETAIL = (
    '<dl class="scholarship04"><dt style=\'display:none;\'></dt><dd>'
    '<p><span><strong>• 신청기간</strong></span></p><p><b>2026. 10. 19. ~ 2026. 11. 06. </b></p><br><br>'
    '<p><span><strong>• 선발인원</strong></span></p><p><b>총 2명</b></p><br><br>'
    '<p><span><strong>• 장학혜택</strong></span></p><p><b>[장학금지급] 최대 200 만원 (생"></dd></dl>'
)


def test_dreamspon() -> None:
    print("드림스폰")
    page = ("<table><tbody>"
            + _ds_row("9264", "신주장학재단 대학생 생활비 장학", "신주장학재단", ["장학금", "대학생", "추천서"])
            + _ds_row("9263", "양평군장학회 학자금대출 이자지원", "양평군장학회", ["대출지원", "대학생"])
            + _ds_row("8853", "의왕시 청년 이사비지원", "의왕시", ["기타지원", "청년", "지역기준"])
            + _ds_row("5134", "첫번째 장학금 받는 꿀팁1", "드림스폰", [])
            + _ds_row("9271", "서귀포시 남원읍 인재양성 꿈 장학 (2026년)", "서귀포시 남원읍", ["장학금", "중학생"])
            + "</tbody></table>")
    rows = dreamspon.parse_list(page)
    check("목록 행", (rows[0]["idx"], rows[0]["name"], rows[0]["org"], rows[0]["tags"]),
          ("9264", "신주장학재단 대학생 생활비 장학", "신주장학재단", ["장학금", "대학생", "추천서"]))
    check("장학 글만 (이사비·꿀팁 빼고)",
          [r["idx"] for r in rows if dreamspon.wanted(r)], ["9264", "9263", "9271"])
    det = dreamspon.parse_detail(DS_DETAIL)
    check("글 요약 칸 (잘린 혜택 꼬리는 떼어 냄)", det,
          {"start": "2026-10-19", "end": "2026-11-06", "quota": "총 2명", "benefit": "[장학금지급] 최대 200 만원"})

    grad_page = "<table>" + _ds_row("9266", "한국여성재단 실천여성학 펠로우십 장학", "한국여성재단", ["장학금", "대학원생"]) + "</table>"
    details = {"9264": det, "9263": det, "9271": {**det, "end": "2026-11-01"}, "9266": det, "9999": det}
    # '대학생' 검색에는 서귀포(초·중) 글이 안 걸린다고 치고, 목록에 #초등학생 #중학생 만 보여도 실제로는
    # 대학생을 뽑는 글(9999)은 '대학생' 검색에 걸리므로 받는다
    hidden = "<table>" + _ds_row("9999", "고창군장학재단 장학 (2026년)", "고창군장학재단", ["장학금", "초등학생", "중학생"]) + "</table>"
    pages = {("대학생", 1): page.replace(_ds_row("9271", "서귀포시 남원읍 인재양성 꿈 장학 (2026년)", "서귀포시 남원읍",
                                                 ["장학금", "중학생"]), "") + hidden,
             ("대학원생", 1): grad_page}
    got = dreamspon.collect(TODAY, list_page=lambda lv, no: pages.get((lv, no), ""), detail=lambda idx: details[idx])
    check("대학생·대학원생 검색에 걸린 장학 글만", [g["url"].rsplit("=", 1)[1] for g in got], ["9264", "9263", "9999", "9266"])
    shinju, loan, gochang, grad = got
    check("목록 태그가 잘려 #중학생 만 보여도 대학생 검색에 걸리면 대학 재학생 조건 통과",
          logic.matches({"level": "재학생"}, gochang), True)
    check("대학원생에만 걸린 글은 대학 재학생 조건에서 빠지고 대학원 조건엔 맞음",
          (logic.matches({"level": "재학생"}, grad), logic.matches({"level": "대학원"}, grad)), (False, True))
    got2 = dreamspon.collect(TODAY, list_page=lambda lv, no: page if (lv, no) == ("대학생", 1) else "",
                             detail=lambda idx: details[idx])
    check("마감 지난 글은 뺌", [g["url"].rsplit("=", 1)[1] for g in got2], ["9264", "9263"])
    try:
        dreamspon.collect(TODAY, list_page=lambda lv, no: "<html>바뀐 화면</html>", detail=lambda idx: det)
        check("목록 형식이 바뀌면 오류로 남김", "조용히 0건", "오류")
    except dreamspon.DreamsponError:
        check("목록 형식이 바뀌면 오류로 남김", "오류", "오류")
    profile = {"regions": "부산", "purpose": "living", "exclude_loans": True}
    check("이름에 생활비 → 생활비 장학금, 지역 무관", (logic.purpose(shinju), logic.matches(profile, shinju)), ("living", True))
    check("대출이자 지원은 대출로 빠짐", logic.is_loan(loan), True)
    remote = dreamspon.to_item(rows[4], det)
    check("기관·이름에 지명이 있으면 그 지역 장학금", logic.region_verdict(profile, remote), "no")

    base = [item("재단법인 신주장학재단", "대학생 장학금", "2025-10-01", "2025-10-31"),
            item("(재)두산연강재단", "장학생", "2026-10-14", "2026-11-13")]
    board = {**item("대한환경공학회", "에코니티 장학 공고", "2026-10-19", "2026-11-20"),
             "notice_title": "에코니티 장학 공고", "source_id": "x", "source": "게시판"}
    ds = lambda org, name, end: {**dreamspon.to_item({"idx": name, "name": name, "org": org, "tags": ["장학금"]},
                                                      {**det, "end": end})}
    out = logic.merge(base, [ds("두산연강재단", "두산연강재단 장학 (2027년)", "2026-11-13"),
                             ds("대한환경공학회", "에코니티·대한환경공학회 우수학생 장학", "2026-11-20"),
                             ds("신주장학재단", "신주장학재단 대학생 생활비 장학", "2026-11-06"),
                             board])
    check("CSV·게시판에 같은 기관·마감이 있으면 드림스폰 것은 버림",
          sorted(x.get("source", "csv") for x in out), ["csv", "csv", "게시판", "드림스폰"])
    new = [x for x in out if x.get("source") == "드림스폰"][0]
    check("기관의 장학금이 하나면 그 장학금의 새 회차로(☆ 이어짐)", new["series"], base[0]["series"])
    check("새 회차로 붙여도 드림스폰 이름을 지켜 '생활비' 조건이 그대로 맞음",
          (new["name"], logic.matches(profile, new)), ("신주장학재단 대학생 생활비 장학", True))
    notes = logic.plan_notifications(out, profile=profile, settings={"notify_new": True}, stars=[],
                                     known_ids={x["id"] for x in base}, sent=set(), today=TODAY)
    check("병합 결과에서 신주 장학금이 '새 장학금' 알림 대상", [(n["kind"], [i["name"] for i in n["items"]]) for n in notes],
          [("new", ["신주장학재단 대학생 생활비 장학"])])
    two = logic.merge([item("가나재단", "A 장학금", "2026-10-01", "2026-11-20")],
                      [ds("가나재단", "가나재단 B 장학", "2026-11-20"), ds("가나재단", "가나재단 A 장학 (2026년)", "2026-11-20")])
    check("같은 기관·같은 마감이라도 이름이 다르면 둘 다 남김(같은 이름은 버림)", sorted(x["name"] for x in two),
          ["A 장학금", "가나재단 B 장학"])
    gn = logic.merge([item("경상남도장학회", "도내 대학 해외교환 장학생", "2026-04-06", "2026-12-18"),
                      item("(재)한국장학재단", "푸른등대 키움증권 기부장학금", "2026-10-22", "2026-11-12")],
                     [ds("경상남도장학회", "경상남도 대학 해외 교환장학생 모집", "2026-12-18"),
                      ds("한국장학재단", "푸른등대 한국가스공사 기부장학금", "2026-11-12")])
    same_org_end = logic.merge([item("가나재단", "인재육성 등록금 장학금", "2026-10-01", "2026-11-20"),
                                item("(재)한국장학재단", "푸른등대 기부장학금(한국가스공사)", "2026-10-22", "2026-11-12")],
                               [ds("가나재단", "인재육성 생활비 장학금", "2026-11-20"),
                                ds("한국장학재단", "푸른등대 기부장학금(키움증권)", "2026-11-12"),
                                ds("한국장학재단", "푸른등대 기부장학금 (2026년 2학기)", "2026-11-12")])
    check("지원 용도(생활비↔등록금)·괄호 속 고유명(키움증권↔한국가스공사)이 다르면 둘 다 남기고, 연도 괄호만 다른 건 버림",
          [x["name"] for x in same_org_end if x.get("source") == "드림스폰"],
          ["인재육성 생활비 장학금", "푸른등대 기부장학금(키움증권)"])
    check("적는 방식만 다른 같은 이름은 버리고, 앞부분만 같은 다른 장학금은 남김",
          [x["name"] for x in gn if x.get("source") == "드림스폰"], ["푸른등대 한국가스공사 기부장학금"])
    school = {**item("부경대학교", "2026년 2학기 푸른등대 기부장학금(2차) 신규장학생 선발 안내(~11.12.)", "2026-10-22", "2026-11-12"),
              "notice_title": "2026년 2학기 푸른등대 기부장학금(2차) 신규장학생 선발 안내(~11.12.)", "source_id": "pknu_main",
              "school_board": True, "source": "부경대 등록·장학 공지"}
    out2 = logic.merge([], [school, ds("한국장학재단", "푸른등대 기부장학금 (2026년 2학기)", "2026-11-12")])
    check("학교가 다시 올린 같은 공고(이름·마감 같음)가 있으면 드림스폰 것은 버림", [x["source"] for x in out2],
          ["부경대 등록·장학 공지"])


NOTICE_TEXT = """
2027년도 제2기 장학생 선발 공고
1. 선발 인원 : 총 90 명
   1   대 학 생        50명    총 5,000,000 원
2. 선발 대상
 가. 지원 자격 : 엔지니어링 및 에너지 관련 학과 재학생
    1) 국내 4 년제 대학 3학기 이상 재학 중인 자
    2) 평균 평점 3.0 이상인 자
3. 선발 절차
 가. 서류 전형
4. 제출 서류
             1. 장학금 지원서(재단 양식) 1 부
             2. 재학증명서 및 성적증명서 각 1 부
5. 신청 방법 : 재단 이메일 접수
□ 지원자격 및 제출서류(학부).hwp
"""


def test_details() -> None:
    print("공고 상세 읽기")
    got = boards.details(NOTICE_TEXT)
    check("선발 인원은 제목 줄 뒤 글자부터", got.get("quota", "").splitlines()[0], "총 90 명")
    check("지원 자격은 아래 줄까지, 다음 큰 제목(3.) 앞에서 끊음", got.get("special"),
          "엔지니어링 및 에너지 관련 학과 재학생\n1) 국내 4 년제 대학 3학기 이상 재학 중인 자\n2) 평균 평점 3.0 이상인 자")
    check("제출 서류는 번호 붙은 줄도 모음(제목보다 깊은 줄)", got.get("documents"),
          "1. 장학금 지원서(재단 양식) 1 부\n2. 재학증명서 및 성적증명서 각 1 부")
    check("신청 방법", got.get("how"), "재단 이메일 접수")
    check("첨부 이름 줄은 제목으로 보지 않음", "학부" in got.get("special", ""), False)

    page = "\n".join([
        "등록금안내", "장학제도", "등록금안내", "2026 푸른등대 기부장학금 선발 안내", "학생복지과",
        "2026 푸른등대 기부장학금 선발 안내",
        "한국장학재단에서 2026년 2학기 푸른등대 기부장학금 신규장학생을 아래와 같이 선발하오니 많은 신청 바랍니다."
        " 저소득층 대학생에게 학기당 생활비 250만 원을 지원합니다. 신청은 재단 누리집에서 받습니다.",
        "- 신청방법: 한국장학재단 누리집", "이전글", "등록금안내 장학 일정",
    ])
    body = boards.content_of(page, "2026 푸른등대 기부장학금 선발 안내")
    check("메뉴·이전글을 덜어 낸 본문", ("등록금안내" in body, "신청방법" in body), (False, True))
    check("메뉴의 '등록금안내' 가 지원 내용 요약에 안 섞임", "등록금안내" in boards._excerpt(body), False)
    check("제목을 못 찾으면 본문 그대로", boards.content_of(page, "다른 글 제목입니다"), page)

    post = ("<h3>2026 정효택 장학생 선발 계획</h3><p>작성일 2026-10-14</p><p>신청기간: 2026. 10. 14. ~ 10. 19.</p>"
            + "<p>지원자격, 제출서류 등 세부사항은 붙임 모집공고 참조 바랍니다. 학과 사무실로 문의하세요."
            + " 장학생 선발 계획을 안내드리니 많은 신청 바랍니다.</p>" * 3
            + '<a href="/down.php?f=1">모집공고.hwpx</a>')
    fetcher = FakeFetcher({
        "down.php": _hwpx("○ 선발인원: 8명\n○ 지원자격: 학부 3, 4학년 재학생\n○ 제출서류: 지원서 1부\n○ 장학금액: 2,000,000원(생활비지원)"),
        "view": post.encode(),
    })
    got = boards.read_post(fetcher, {"title": "2026 정효택 장학생 선발 계획", "url": "https://x.example/view",
                                     "posted": D("2026-10-14")})
    check("본문에 날짜가 있어도 상세는 공고문에서", (got["end"], got["details"].get("quota"), got["details"].get("special")),
          (D("2026-10-19"), "8명", "학부 3, 4학년 재학생"))
    check("'지원자격, 제출서류 등은 붙임 참조' 같은 묶음 제목은 내용으로 안 씀", "세부사항" in got["details"].get("special", ""), False)
    check("상세만 보려고 연 공고문은 생활비 판정에 안 씀", "생활비" in got["excerpt"], False)

    got = boards.details("○ 다음 사항에 해당할 시, 서류심사를 진행하지 않음\n- 필수 제출 서류 누락\n- 허위 기재\n"
                         "3. 제출 서류\n○ (필수) 온라인 지원서 1부, 대학교 성적증명서\n4. 유의 사항\n○ 기타")
    check("'필수 제출 서류 누락' 같은 문장 속 낱말은 제목이 아님 — 뒤의 진짜 '3. 제출 서류' 를 읽음",
          got.get("documents"), "○ (필수) 온라인 지원서 1부, 대학교 성적증명서")

    post = ("<h3>2026 인석 장학생 선발 안내</h3><p>작성일 2026-10-14</p><p>접수 마감: 2026. 11. 26.까지</p>"
            + "<p>자세한 지원 자격과 제출 서류는 붙임 공고문을 꼭 확인하여 주시기 바랍니다. 많은 지원 바랍니다.</p>" * 3
            + '<a href="/down.php?f=2">선발공고.hwpx</a>')
    fetcher = FakeFetcher({
        "down.php": _hwpx("○ 지원자격: 4년제 대학 재학생\n○ 제출서류: 지원서 1부\n○ 선발인원: 10명"),
        "view": post.encode(),
    })
    got = boards.read_post(fetcher, {"title": "2026 인석 장학생 선발 안내", "url": "https://x.example/view",
                                     "posted": D("2026-10-14")})
    check("본문엔 마감만, 공고문엔 날짜 없이 자격·서류만 있어도 상세는 공고문에서",
          (got["end"], got["details"].get("special"), got["details"].get("documents")),
          (D("2026-11-26"), "4년제 대학 재학생", "지원서 1부"))

    print("공고 대상(학적)")
    check("대학원만 말하는 제목은 대학원 과정으로", boards.grades_of("2027년 의생명과학분야 대학원 장학생 선발 안내"),
          ["석사신입생(1학기)", "석사2학기이상", "박사과정"])
    check("'대학 장학생' 은 학부", boards.grades_of("2027년 의생명과학분야 대학 장학생 선발 안내"), [])
    grad = {"name": "대학원 장학생", "grades": boards.grades_of("2027년 의생명과학분야 대학원 장학생 선발 안내")}
    check("대학원 공고는 '재학생' 조건에서 빠짐", logic.matches({"level": "재학생"}, grad), False)
    check("중학교 2학년만 뽑는 구 장학회 공고는 대학생 공고가 아님",
          boards.for_college({"notice_title": "남구장학회 해외역사문화체험 장학생 선발계획 공고",
                              "special": "- 남구에 3년 이상 거주하는 중학교 2학년 재학생"}), False)
    check("고교·대학 둘 다 뽑는 공고는 남김",
          boards.for_college({"notice_title": "기장군 장학금 신청 알림", "special": "고등학생 및 대학생"}), True)
    fetcher = FakeFetcher({
        "no=7": ("<h3>남구장학회 해외역사문화체험 장학생 선발계획 공고</h3><p>작성일 2026-10-20</p>"
                 "<p>○ 신청기간: 2026. 10. 20. ~ 11. 20.</p><p>○ 지원 자격 : 남구에 3년 이상 거주하는 중학교 2학년 재학생</p>"
                 + "<p>남구장학회에서 미래 인재를 위한 해외 역사문화 체험 장학생을 아래와 같이 선발하오니 많은 신청 바랍니다.</p>" * 2).encode(),
        "list": ('<table><tr><td><a href="/b?no=7">남구장학회 해외역사문화체험 장학생 선발계획 공고</a></td>'
                 '<td>26.10.20</td></tr></table>').encode(),
    })
    stats: dict = {}
    got = boards.collect([{"id": "namgu", "label": "부산 남구장학회", "org": "(재)부산광역시 남구장학회",
                           "region": "부산광역시 남구", "url": "https://www.bsnamgu.go.kr/list"}],
                         today=TODAY, fetcher=fetcher, stats=stats)
    check("수집할 때 초·중·고 전용 공고는 뺌", (got, stats["namgu"]["picked"], stats["namgu"]["items"]), ([], 1, 0))

    print("게시판 형식")
    rows = boards.list_posts('<table><tr><td><a href="/v?n=1">2026년도 하반기 기장군 장학금 신청 알림</a></td>'
                             '<td>051-709-4000</td><td>26.09.18</td></tr></table>', "https://www.gijang.go.kr/l")
    check("두 자리 연도 날짜('26.09.18')를 게시일로, 전화번호는 날짜로 안 봄", rows[0]["posted"], D("2026-09-18"))
    rows = boards.list_posts(
        '<table><tr><td><a href="/af/Detail.do" onclick="fnDetail(11306); return false;">2027년 아산장학생 선발 안내</a></td>'
        '<td>2026.10.01</td></tr><tr><td><a href="/af/Detail.do" onclick="fnDetail(11305); return false;">'
        '2027년 북한이탈청소년장학생 선발 안내</a></td><td>2026.10.01</td></tr></table>',
        "https://www.asanfoundation.or.kr/af/List.do", [r"fnDetail\((\d+)\)", "https://x.example/Detail.do?idx={}"])
    check("글 번호가 onclick 에만 있는 게시판", [r["url"] for r in rows],
          ["https://x.example/Detail.do?idx=11306", "https://x.example/Detail.do?idx=11305"])
    files = boards.attachments(
        """<a href="javascript:file_download('/download?db=1&id=5350&no=0', '안내문.pdf');">붙임1) 추천 안내문.pdf (115.2K)</a>""",
        "https://www.kosffl.or.kr/news/notice?page=view&id=5350")
    check("javascript:file_download('…') 첨부는 안의 주소로", [u for u, _ in files],
          ["https://www.kosffl.or.kr/download?db=1&id=5350&no=0"])
    check("그누보드 '… H 인기글 (미리보기)' 꼬리 떼기",
          boards.clean_title("인재림(人材林) 제7기 지원자 모집 H 인기글 인재림(人材林) 제7기 지원자 모집 중~! 장학 프로그램"),
          "인재림(人材林) 제7기 지원자 모집")
    check("제목을 두 칸에 적은 목록", boards.clean_title("부산지역인재 장학금 공고 부산지역인재 장학금 공고"), "부산지역인재 장학금 공고")
    kfas = {"want": r"장학|지원자\s*모집"}
    check("장학 재단 게시판은 '장학' 없는 모집 글도, 미리보기의 '장학' 으로는 안 받음",
          [p["url"] for p in boards.pick(kfas, [
              {"title": "인재림(人材林) 제7기 지원자 모집 H 인기글", "posted": D("2026-10-07"), "url": "a"},
              {"title": "드림렉처 학교 신청 접수 H 인기글 재단의 장학프로그램을 통해", "posted": D("2026-08-21"), "url": "b"},
          ], TODAY)], ["a"])
    item = {"region": "부산광역시 남구", "category": "지역연고", "org": "(재)부산광역시 남구장학회"}
    check("구·군 장학회 공고는 그 구 주민 것으로", (logic.region_verdict({"regions": "부산"}, item),
          logic.region_verdict({"regions": "부산, 해운대구"}, item), logic.region_verdict({"regions": "광주"}, item)),
          ("ok", "no", "no"))


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

    # 리뷰 재현: 같은 학교 기관명의 CSV 장학금 + 제목에 학교 이름이 든 학교 공고 둘, 마감일 모두 같음
    alumni = item("부경대학교", "동문회 장학금", "2026-10-01", "2026-11-30")
    def school(title):
        return {**notice(title, "2026-10-15", "2026-11-30"), "org": "부경대학교"}
    fill, light = school("부경대학교 더채움 장학금 안내"), school("부경대학교 푸른등대 기부장학금 안내")
    out = logic.merge([alumni], [fill, light])
    check("학교 이름만 같다고 같은 장학금으로 합치지 않음(3건 그대로)", len(out), 3)
    check("CSV 장학금에 엉뚱한 공고 링크가 붙지 않음", out[0].get("notice_url"), None)
    # 외부 기관 공고 재게시는 그대로 붙되, 한 항목에 두 번째 공고는 붙지 않음
    busan = item("부산광역시청", "부산지역인재 장학금", "2026-10-14", "2026-10-28")
    r1 = {**school("2026년 부산지역인재 장학금 생활장학금 신청 공고"), "end": "2026-10-28"}
    r2 = {**school("부산광역시청 부산지역인재 장학금 추가 안내"), "end": "2026-10-28"}
    out = logic.merge([busan], [r1, r2])
    check("한 장학금에는 공고 하나만, 나머지는 따로", (len(out), out[0].get("notice_url")), (2, r1["url"]))

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
    test_dreamspon()
    test_review_regressions()
    test_details()
    if FAILURES:
        print(f"\n실패 {len(FAILURES)}건")
        return 1
    print("\n모두 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
