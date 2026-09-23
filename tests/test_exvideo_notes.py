"""요약정리본(/api/exvideo/notes) 테스트.

    python3 tests/test_exvideo_notes.py

여기서 고정하는 것 — 사용자가 실제로 요구한 것들이다.
  1. PDF 텍스트 추출에 LLM 이 쓰이지 않는다 (PyMuPDF 만).
  2. 인덱스는 원문 표기(제목·수식·예제)를 보존하고, 각 섹션이 PDF 쪽수와
     전사 타임코드를 갖는다.
  3. **정리본을 만들 때 원본 전사/PDF 전문이 입력에 들어가지 않는다.**
     ← "나중에 또 요청할 때 다시 읽게 하면 안 돼" 가 코드로 지켜지는지.
  4. 다만 섹션을 콕 집으면 그 구간만 다시 꺼내 쓸 수 있다.
  5. 만들어진 PDF 에서 한글이 깨지지 않는다.

LLM 은 가짜 프로바이더로 대체한다. 네트워크도 Ollama 도 필요 없다.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="unifi-notes-test-")
os.environ["UNIFI_DATA_DIR"] = _TMP
os.environ.pop("UNIFI_PASSWORD", None)

from apps.exvideo.exvideo.notes import extract, index as nidx, render as nrender  # noqa: E402
from apps.exvideo.exvideo.notes.llm import LLMResult  # noqa: E402

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: got {got!r}, want {want!r}")
        FAILURES.append(label)


def ok(label: str, cond, detail: str = "") -> None:
    check(label + (f" ({detail})" if detail else ""), bool(cond), True)


# ───────────────────────────── 재료 ─────────────────────────────

LECTURE_MD = """# 3주차 강의자료

## 1장. 함수의 극한

**정의 1.1** lim_{x->a} f(x) = L 의 엡실론-델타 정의.

**예제 1.3** lim_{x->2} (x^2-4)/(x-2) = 4.

---

## 2장. 연속성

**정의 2.1** lim_{x->a} f(x) = f(a) 이면 연속이다.

**예제 2.3** x^3-x-1=0 은 (1,2) 에서 근을 갖는다.
"""

TRANSCRIPT = (
    "[00:00:00] 오늘은 함수의 극한부터 합니다. 엡실론 델타 논법이 나옵니다.\n"
    "[00:04:12] 예제 1.3 은 인수분해해서 약분하면 답이 4 입니다.\n"
    "[00:08:00] 이제 연속성으로 넘어갑니다. 정의가 세 가지를 요구합니다.\n"
    "[00:12:30] 예제 2.3 은 중간값 정리로 근의 존재를 보이는 문제입니다.\n"
    # 토큰 절감은 원본이 어느 정도 커야 드러난다. 장황한 구어체 설명을 덧붙여
    # '원본은 길고 인덱스는 짧다' 는 실제 상황을 만든다.
    + "".join(
        f"[00:{20 + i:02d}:00] 조금 더 풀어서 설명하겠습니다. 여기서 중요한 건 극한이"
        " 존재한다는 말과 함숫값이 정의된다는 말이 서로 다르다는 점입니다."
        " 시험에서는 이 둘을 섞어서 물어보니까 꼭 구분해 두세요.\n"
        for i in range(30)
    )
)

# 가짜 LLM 이 조각별로 돌려줄 색인 결과
FAKE_PDF_JSON = {"sections": [
    {"title": "1장. 함수의 극한", "page": 1, "time": None,
     "concepts": ["엡실론-델타 논법"], "formulas": ["lim_{x->a} f(x) = L"],
     "examples": ["예제 1.3"], "summary": "극한의 정의를 다룬다."},
    {"title": "2장. 연속성", "page": 2, "time": None,
     "concepts": ["연속"], "formulas": ["lim_{x->a} f(x) = f(a)"],
     "examples": ["예제 2.3"], "summary": "연속의 정의를 다룬다."},
]}
FAKE_TRANSCRIPT_JSON = {"sections": [
    {"title": "함수의 극한", "page": None, "time": "00:00:00",
     "concepts": ["좌극한"], "formulas": [], "examples": [],
     "summary": "엡실론 델타를 말로 설명한다."},
    {"title": "연속성", "page": None, "time": "00:08:00",
     "concepts": ["불연속"], "formulas": [], "examples": [],
     "summary": "연속 정의의 세 조건을 짚는다."},
]}

RENDER_MD = """## 목차
- 1장. 함수의 극한 (p.1, 00:00:00)
- 2장. 연속성 (p.2, 00:08:00)

## 핵심요약
극한과 연속을 다룬 강의다. **엡실론-델타** 정의가 출발점이다.

1. 극한이 존재해야 한다.
2. 함숫값이 정의돼야 한다.
"""


class FakeProvider:
    """호출 기록을 남기는 가짜 LLM. 무엇이 입력으로 들어갔는지 검사하려고 쓴다."""

    name = "fake"
    model = "fake-1"

    def __init__(self):
        self.calls: list[str] = []
        self.seen: set[str] = set()

    def complete(self, system, user, *, json_mode=False, max_tokens=2048):
        self.calls.append(user)
        if not json_mode:
            body = RENDER_MD
        else:
            # 실제로도 모든 조각에 새 절 제목이 있는 건 아니다. 조각 종류별로
            # 첫 번째에서만 절을 돌려주고 나머지는 빈 결과를 낸다.
            kind = "pdf" if "[p." in user else "transcript"
            if kind in self.seen:
                body = '{"sections":[]}'
            else:
                self.seen.add(kind)
                body = json.dumps(
                    FAKE_PDF_JSON if kind == "pdf" else FAKE_TRANSCRIPT_JSON,
                    ensure_ascii=False)
        # 토큰 수는 프로바이더가 보고하는 값 — 여기서는 문자 수로 흉내만 낸다
        return LLMResult(text=body, input_tokens=len(user) // 3,
                         output_tokens=len(body) // 3, provider=self.name, model=self.model)


def install_fake() -> FakeProvider:
    fake = FakeProvider()
    nidx.get_provider = lambda *a, **k: fake
    nrender.get_provider = lambda *a, **k: fake
    return fake


# ───────────────────────────── 테스트 ─────────────────────────────


def test_extract_without_llm(pdf_path: str) -> None:
    print("\n[1] PDF 추출 — LLM 없이 PyMuPDF 만으로")
    pages = extract.pdf_pages(pdf_path)
    ok("쪽이 잡힌다", len(pages) >= 1, f"{len(pages)}쪽")
    text = "\n".join(p.text for p in pages)
    ok("한글 본문이 그대로 나온다", "함수의 극한" in text)
    ok("수식 표기가 보존된다", "lim_{x->a}" in text)
    check("스캔본으로 오판하지 않는다", extract.pdf_is_scanned(pages), False)


def test_transcript_chunking() -> None:
    print("\n[2] 전사 조각내기 — 원본으로 되돌아갈 좌표가 맞는가")
    chunks = extract.chunk_transcript(TRANSCRIPT, target_chars=80)
    ok("여러 조각으로 나뉜다", len(chunks) > 1, f"{len(chunks)}조각")
    check("첫 조각 시작 타임코드", chunks[0].time_start, "00:00:00")
    for ch in chunks:
        s, e = ch.char_span
        ok(f"{ch.time_start} 구간이 원문과 일치", TRANSCRIPT[s:e].strip() == ch.text)
    check("마지막 조각이 원문 끝까지", chunks[-1].char_span[1], len(TRANSCRIPT))


def _sec(title, **kw) -> dict:
    base = {"title": title, "concepts": [], "formulas": [], "examples": [], "summary": "",
            "pages": [], "time_start": "", "time_end": "", "char_span": [0, 0]}
    base.update(kw)
    return base


def test_merge() -> None:
    print("\n[3] PDF 섹션 + 전사 섹션 합치기")
    pdf_secs = [
        # 강의자료는 '4장. 미분계수와 도함수', 강사는 '4장 미분계수' 라고 부른다.
        # 앞이 겹치는 경우를 놓치면 인덱스가 두 배로 부푼다 (실제로 겪은 버그).
        _sec("1장. 함수의 극한", concepts=["엡실론-델타 논법"], formulas=["f"],
             summary="정의.", pages=[1]),
        _sec("4장. 미분계수와 도함수", concepts=["순간변화율"], summary="미분.", pages=[4]),
    ]
    tr_secs = [
        _sec("함수의 극한", concepts=["좌극한"], summary="말로 설명.",
             time_start="00:00:00", time_end="00:04:12", char_span=[0, 60]),
        _sec("4장 미분계수", concepts=["접선의 기울기"], summary="미분 설명.",
             time_start="00:10:00", time_end="00:20:00", char_span=[60, 120]),
        # 강의자료에 없고 내용도 실린 절 — 남아야 한다
        _sec("현장 보충: 로그미분법", concepts=["로그미분법"], formulas=["ln y = x ln x"],
             examples=["y = x^x"], summary="보충 설명.",
             time_start="00:25:00", time_end="00:28:00", char_span=[120, 180]),
        # 지나가는 한마디 — 직전 절에 흡수되어야 한다
        _sec("다음 시간 공지", summary="공지.",
             time_start="00:30:00", time_end="00:32:00", char_span=[180, 200]),
    ]
    merged = nidx._merge_sections(pdf_secs, tr_secs)
    titles = [s["title"] for s in merged]
    check("합칠 건 합치고 남길 건 남긴다", titles,
          ["1장. 함수의 극한", "4장. 미분계수와 도함수", "현장 보충: 로그미분법"])

    first = merged[0]
    check("합쳐진 섹션이 PDF 쪽수를 갖는다", first["pages"], [1])
    check("합쳐진 섹션이 타임코드도 갖는다", first["time_start"], "00:00:00")
    check("개념이 양쪽에서 모인다", sorted(first["concepts"]), ["엡실론-델타 논법", "좌극한"])
    check("앞이 겹치는 제목도 합쳐진다", sorted(merged[1]["concepts"]),
          ["순간변화율", "접선의 기울기"])
    ok("흡수된 토막의 내용은 시간상 직전 절에 남는다", "공지." in merged[2]["summary"],
       merged[2]["summary"])
    check("id 가 다시 매겨진다", [s["id"] for s in merged], ["s01", "s02", "s03"])


def test_index_and_render(pdf_path: str) -> dict:
    print("\n[4] 인덱스 생성 → 정리본 생성")
    fake = install_fake()
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    sid = nidx.create_source("3주차", pdf_bytes=pdf_bytes, pdf_name="l.pdf",
                             transcript_text=TRANSCRIPT)
    index = nidx.build_index(sid)

    check("중복 없이 2개 섹션", len(index["sections"]), 2)
    s1 = index["sections"][0]
    check("섹션 제목이 원문 그대로", s1["title"], "1장. 함수의 극한")
    check("수식이 원문 그대로", s1["formulas"], ["lim_{x->a} f(x) = L"])
    check("PDF 쪽수가 붙는다", s1["pages"], [1])
    check("타임코드가 붙는다", (s1["time_start"], s1["time_end"]), ("00:00:00", "00:08:00"))
    ok("인덱스 토큰이 실측된다", index["tokens"]["input"] > 0, str(index["tokens"]))
    check("버전 1", index["version"], 1)

    n_index_calls = len(fake.calls)
    meta = nrender.generate(sid, parts=["toc", "summary"])
    render_prompt = fake.calls[-1]

    print("\n[5] 정리본 입력에 원본이 들어가지 않는가 — 이 앱의 핵심 규칙")
    ok("전사 원문이 프롬프트에 없다",
       "오늘은 함수의 극한부터 합니다" not in render_prompt)
    ok("PDF 본문 문장이 프롬프트에 없다",
       "엡실론-델타 정의" not in render_prompt)
    ok("인덱스 섹션 제목은 들어 있다", "1장. 함수의 극한" in render_prompt)
    raw_chars = len(TRANSCRIPT) + len(LECTURE_MD)
    ok("정리본 프롬프트가 원본보다 짧다",
       len(render_prompt) < raw_chars, f"{len(render_prompt)}자 < {raw_chars}자")
    ok("정리본 호출은 딱 한 번", len(fake.calls) - n_index_calls == 1)

    print("\n[6] 섹션 단위 선택적 재조회")
    raw = nidx.load_raw_sections(sid, ["s01"])
    ok("해당 섹션 원문이 나온다", "함수의 극한" in raw)
    ok("다른 섹션 전사는 안 딸려온다", "예제 2.3 은 중간값 정리로" not in raw)
    full = len(TRANSCRIPT) + sum(len(p["text"]) for p in nidx._read_raw(sid, "pages.json"))
    ok("전체 원본보다 작다", len(raw) < full, f"{len(raw)}자 < {full}자")

    fake.calls.clear()
    nrender.generate(sid, parts=["examples"], raw_sections=["s01"])
    ok("콕 집으면 그 섹션 원문은 들어간다", "오늘은 함수의 극한부터 합니다" in fake.calls[-1])
    ok("그래도 2장 전사는 안 들어간다", "예제 2.3 은 중간값 정리로" not in fake.calls[-1])

    print("\n[7] 사용량 기록")
    usage = nidx.read_usage(sid)
    check("index 1회 + render 2회 기록", [u["stage"] for u in usage],
          ["index", "render", "render"])
    ok("재요청 입력이 1차보다 적다",
       usage[1]["input_tokens"] < usage[0]["input_tokens"],
       f"{usage[1]['input_tokens']} < {usage[0]['input_tokens']}")
    return meta


def test_normalize() -> None:
    print("\n[8] 조판 전 정리 — 모델이 흘리는 찌꺼기를 걷어내는가")
    messy = (
        "```markdown\n"
        "# 제목\n"
        "1. ## [s01] 1장. 수열의 극한 (p.1-1)\n"
        "- **문제**: \\(x^3 - x - 1 = 0\\) 의 근을 보여라.\n"
        "- \\(\\lim_{x \\to 1} f(x) = \\frac{x^2-1}{x-1} = 2\\)\n"
        "```"
    )
    got = nrender.normalize_markdown(messy)
    ok("코드펜스가 사라진다", "```" not in got)
    ok("목록 안 제목표시가 사라진다", "1. [s01] 1장. 수열의 극한 (p.1-1)" in got, got)
    ok("LaTeX 구분자가 사라진다", "\\(" not in got and "\\)" not in got)
    ok("분수가 평문이 된다", "(x^2-1)/(x-1)" in got, got)
    ok("화살표가 평문이 된다", "->" in got and "\\to" not in got)
    ok("본문은 살아 있다", "x^3 - x - 1 = 0" in got)


def test_claude_cli_stream() -> None:
    """계정 연동 클로드 — 답변이 잘려 이어질 때 앞부분을 잃지 않는가.

    실제로 났던 사고다. `--output-format json` 의 `result` 에는 마지막 조각만
    담겨서, 10쪽짜리 정리본의 앞 절반이 통째로 사라진 채 PDF 가 나왔다.
    여기서는 그 스트림을 그대로 재현해 고정한다.
    """
    print("\n[9] 계정 연동 클로드 — 이어 쓴 답변을 온전히 모으는가")
    from apps.exvideo.exvideo.notes.llm import ClaudeCLIProvider, _join_overlap

    check("겹치지 않으면 그냥 붙인다", _join_overlap("가나", "다라"), "가나다라")
    check("겹친 만큼만 덜어낸다", _join_overlap("49줄\n50", "50줄\n51"), "49줄\n50줄\n51")
    check("한쪽이 비면 나머지", _join_overlap("", "다라"), "다라")

    def ev(kind: str, **rest) -> str:
        return json.dumps({"type": kind, **rest})

    def say(text: str) -> str:
        return ev("assistant", message={"content": [{"type": "text", "text": text}]})

    stream = "\n".join([
        ev("system", subtype="init"),
        say(""),                       # 빈 조각은 세지 않는다
        say("# 목차\n1장\n2장"),
        say("2장\n3장"),               # 이어 쓰기 — 경계가 겹친다
        ev("result", is_error=False, result="2장\n3장",
           usage={"input_tokens": 10, "cache_read_input_tokens": 5,
                  "cache_creation_input_tokens": 2, "output_tokens": 7}),
    ])
    text, usage, error, chunks = ClaudeCLIProvider._collect_text(stream)
    check("앞부분이 살아 있다", text, "# 목차\n1장\n2장\n3장")
    check("이어 쓴 횟수를 센다", chunks, 2)
    check("입력 토큰은 캐시까지 합산",
          usage["input_tokens"] + usage["cache_read_input_tokens"]
          + usage["cache_creation_input_tokens"], 17)
    check("오류 없음", error, "")

    err = "\n".join([say("부분 답변"),
                     ev("result", is_error=True, result="rate limit", usage={})])
    _, _, error, _ = ClaudeCLIProvider._collect_text(err)
    ok("오류는 삼키지 않는다", "rate limit" in error, error)


def test_custom_outline_and_design() -> None:
    """사용자가 직접 정한 구성과 조판 설정이 실제로 반영되는가."""
    print("\n[10] 직접 정한 구성 · PDF 모양")

    outline = "1. 한눈에 보기 — 3줄\n2. 꼭 외울 것 — 공식만"
    p = nrender.build_prompt({"title": "T", "version": 1, "sections": []},
                             parts=["toc", "summary"], outline=outline)
    ok("직접 적은 항목이 프롬프트에 들어간다", "한눈에 보기" in p and "꼭 외울 것" in p)
    ok("직접 적었으면 기본 구성은 빠진다", "핵심요약" not in p and "목차" not in p, p[:80])

    p2 = nrender.build_prompt({"title": "T", "version": 1, "sections": []},
                              parts=["summary"], outline="")
    ok("안 적었으면 고른 구성을 쓴다", "핵심요약" in p2)

    d = nrender.resolve_design
    check("기본값", d(None), nrender.DESIGN)
    check("일부만 줘도 나머지는 기본", d({"scale": 1.15})["line"], nrender.DESIGN["line"])
    check("너무 큰 값은 자른다", d({"scale": 99})["scale"], 1.4)
    check("너무 작은 값도 자른다", d({"line": 0.1})["line"], 1.1)
    check("색이 아니면 기본색", d({"accent": "red"})["accent"], nrender.DESIGN["accent"])
    check("정상 색은 통과", d({"accent": "#2563EB"})["accent"], "#2563EB")
    check("숫자가 아니면 통째로 기본값", d({"margin": "넓게"}), nrender.DESIGN)

    # 실제로 조판해서 설정이 먹는지 본다 — 값만 받아두고 안 쓰면 의미가 없다.
    import pymupdf
    sizes = {}
    for name, design in (("small", {"scale": 0.85}), ("big", {"scale": 1.3})):
        path = os.path.join(_TMP, f"design-{name}.pdf")
        nrender.write_pdf("# 제목\n\n본문입니다.", path, title="T", design=design)
        doc = pymupdf.open(path)
        sizes[name] = max(s["size"] for b in doc[0].get_text("dict")["blocks"]
                          for l in b.get("lines", []) for s in l["spans"])
    ok("글자 크기 설정이 PDF 에 반영된다", sizes["big"] > sizes["small"],
       f"{sizes['small']:.1f} < {sizes['big']:.1f}")


def test_pdf_output(meta: dict) -> None:
    print("\n[11] 결과물 PDF — 한글이 깨지지 않는가")
    ok("PDF 가 생겼다", os.path.exists(meta["pdf"]))
    pages = extract.pdf_pages(meta["pdf"])
    text = "\n".join(p.text for p in pages)
    ok("한글 제목이 읽힌다", "핵심요약" in text, repr(text[:80]))
    ok("굵게 표시가 마크다운 기호로 새지 않는다", "**" not in text)
    ok("번호 목록이 살아 있다", "극한이 존재해야 한다" in text)
    ok("쪽번호가 찍힌다", "1" in pages[0].text.splitlines())


def test_api(pdf_path: str) -> None:
    print("\n[12] API 왕복")
    from fastapi.testclient import TestClient
    from server.main import app

    install_fake()
    client = TestClient(app)

    with open(pdf_path, "rb") as f:
        r = client.post("/api/exvideo/notes/sources",
                        data={"title": "API 테스트", "transcript": TRANSCRIPT},
                        files={"pdf": ("l.pdf", f.read(), "application/pdf")})
    check("업로드 200", r.status_code, 200)
    sid = r.json()["source_id"]

    r = client.post(f"/api/exvideo/notes/sources/{sid}/index", json={})
    check("인덱스 작업 시작", r.status_code, 200)
    job = _wait(client, r.json()["job_id"])
    check("인덱스 완료", job["status"], "done")

    r = client.post(f"/api/exvideo/notes/sources/{sid}/render",
                    json={"parts": ["toc", "summary"]})
    job = _wait(client, r.json()["job_id"])
    check("정리본 완료", job["status"], "done")
    render_id = job["result"]["render_id"]

    r = client.get(f"/api/exvideo/notes/sources/{sid}/outputs/{render_id}.pdf")
    check("PDF 내려받기 200", r.status_code, 200)
    ok("진짜 PDF 다", r.content[:4] == b"%PDF")

    r = client.get(f"/api/exvideo/notes/sources/{sid}/outputs/../../../etc/passwd.pdf")
    ok("경로 탈출은 막힌다", r.status_code in (400, 404), str(r.status_code))

    r = client.get("/api/exvideo/notes/sources/zzz")
    check("없는 소스는 404", r.status_code, 404)

    r = client.get(f"/api/exvideo/notes/sources/{sid}")
    body = r.json()
    ok("사용량이 조회된다", len(body["usage"]) == 2, str([u["stage"] for u in body["usage"]]))


def _wait(client, job_id: str, tries: int = 200) -> dict:
    import time
    for _ in range(tries):
        job = client.get(f"/api/exvideo/notes/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            if job["status"] == "error":
                print("    job error:", job["error"])
            return job
        time.sleep(0.05)
    return {"status": "timeout"}


def run() -> None:
    work = tempfile.mkdtemp(prefix="unifi-notes-src-")
    pdf_path = os.path.join(work, "lecture.pdf")
    nrender.write_pdf(LECTURE_MD, pdf_path, title="3주차 강의자료")

    test_extract_without_llm(pdf_path)
    test_transcript_chunking()
    test_merge()
    meta = test_index_and_render(pdf_path)
    test_normalize()
    test_claude_cli_stream()
    test_custom_outline_and_design()
    test_pdf_output(meta)
    test_api(pdf_path)
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        run()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print()
    if FAILURES:
        print(f"실패 {len(FAILURES)}건: " + ", ".join(FAILURES))
        sys.exit(1)
    print("모두 통과")
