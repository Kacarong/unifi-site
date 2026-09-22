"""구조 보존 인덱스 — 원본을 딱 한 번만 읽는 지점.

인덱스는 산문 요약이 아니다. 챕터/소절 제목·핵심 개념·수식·예제는 **원문 그대로**
남기고, 각 항목에 PDF 페이지 번호와 전사 타임코드를 붙인다. 줄이는 것은
설명 문장뿐이다. 그래야 나중에 "예상문제 위주로" 같은 요청이 와도 없는 내용을
지어내지 않는다.

원본은 지우지 않고 `raw/` 에 남겨 두되, 요약정리본을 만들 때 통째로 다시
보내지 않는다. 섹션 단위로만 꺼내 쓴다.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid

from server.paths import data_dir

from . import extract
from .llm import LLMError, get_provider, parse_json

SCHEMA = 1
NOTES_ROOT = data_dir("exvideo", "notes")

# 강의자료에 대응하는 절이 없는 전사 항목 중, 이 개수 이하의 항목(개념+수식+예제)만
# 담긴 것은 독립된 절이 아니라 지나가는 언급으로 보고 직전 절에 흡수시킨다.
FRAGMENT_ITEMS = 2

INDEX_SYSTEM = """당신은 강의자료 색인기입니다. 요약가가 아닙니다.

원문 조각을 받아 그 안의 절(section)들을 JSON 으로 색인합니다.

절대 규칙:
- 제목·핵심 개념어·수식·예제는 원문 표기를 그대로 옮깁니다. 바꿔 쓰지 않습니다.
- 정의·정리·공식은 formulas 에 원문 그대로 넣습니다. 수학 기호가 없어도 넣습니다.
- 원문에 없는 내용을 절대 만들지 않습니다. 없으면 빈 배열로 둡니다.
- 절은 장(chapter) 단위로 잡습니다. 예제 하나, 공지 한 줄을 별도의 절로 만들지
  않습니다. 그런 것은 가장 가까운 장의 examples/summary 에 넣습니다.
- 줄여도 되는 것은 설명 문장뿐입니다. summary 는 두 문장 이내로 줄입니다.
- page 는 그 절이 시작하는 `[p.N]` 의 N 입니다. 원문에 `[p.N]` 이 없으면 null.
- time 은 그 절이 시작하는 `[HH:MM:SS]` 를 그대로 옮깁니다. 없으면 null.
- 한국어로 씁니다.

출력은 아래 스키마의 JSON 객체 하나뿐입니다:
{"sections":[{"title":"원문 제목 그대로","page":1,"time":"00:00:00","concepts":["개념어"],"formulas":["정의/정리/수식"],"examples":["예제"],"summary":"설명 요약"}]}"""


def _slug(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:120]


_NORM = re.compile(r"[^0-9A-Za-z가-힣]+")


def _norm_title(title: str) -> str:
    """제목 대조용 정규화. '1장. 함수의 극한' 과 '함수의 극한' 을 같은 것으로 본다."""
    return _NORM.sub("", title or "")


_CHAPTER = re.compile(r"^\s*(?:제\s*)?\d+\s*(?:장|절|주차)[.\s]*")


def _merge_key_match(a: str, b: str) -> bool:
    """제목이 같은 절을 가리키는가.

    강의자료는 '7장. 평균값 정리와 응용', 강사는 '7장 평균값 정리' 라고 부른다.
    장 번호를 떼고 한쪽이 다른 쪽을 품고 있으면 같은 절로 본다
    (앞이 겹치든 뒤가 겹치든 — 여기서 한쪽만 보면 인덱스가 두 배로 부푼다).
    """
    a = _norm_title(_CHAPTER.sub("", a or ""))
    b = _norm_title(_CHAPTER.sub("", b or ""))
    if not a or not b or min(len(a), len(b)) < 3:
        return False
    return a in b or b in a


def _dedup(*lists) -> list[str]:
    seen, out = set(), []
    for items in lists:
        for item in items or []:
            key = _norm_title(item)
            if key and key not in seen:
                seen.add(key)
                out.append(item)
    return out


# ---------------------------------------------------------------- 저장소


_SID = re.compile(r"^[0-9a-f]{12}$")


def source_dir(source_id: str, *sub: str) -> str:
    # source_id 는 URL 에서 그대로 들어오므로 경로 탈출을 여기서 막는다.
    if not _SID.match(source_id or ""):
        raise ValueError(f"잘못된 source_id: {source_id!r}")
    path = os.path.join(NOTES_ROOT, source_id, *sub)
    os.makedirs(path, exist_ok=True)
    return path


def create_source(title: str, *, pdf_bytes: bytes | None = None, pdf_name: str = "",
                  transcript_text: str = "") -> str:
    if not pdf_bytes and not transcript_text.strip():
        raise ValueError("강의자료 PDF 나 전사 중 최소 하나는 있어야 합니다.")

    source_id = uuid.uuid4().hex[:12]
    raw = source_dir(source_id, "raw")

    pages: list[extract.Page] = []
    if pdf_bytes:
        pdf_path = os.path.join(raw, "lecture.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        pages = extract.pdf_pages(pdf_path)
        with open(os.path.join(raw, "pages.json"), "w", encoding="utf-8") as f:
            json.dump([{"page": p.page, "text": p.text} for p in pages], f, ensure_ascii=False)

    if transcript_text:
        with open(os.path.join(raw, "transcript.txt"), "w", encoding="utf-8") as f:
            f.write(transcript_text)

    meta = {
        "source_id": source_id,
        "title": title or pdf_name or "이름 없는 강의",
        "pdf_name": pdf_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_pages": len(pages),
        "scanned_pdf": bool(pdf_bytes) and extract.pdf_is_scanned(pages),
        "transcript_chars": len(transcript_text),
        "raw_chars": sum(len(p.text) for p in pages) + len(transcript_text),
    }
    _write(source_id, "meta.json", meta)
    return source_id


def _write(source_id: str, name: str, obj) -> str:
    path = os.path.join(source_dir(source_id), name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return path


def _read(source_id: str, name: str):
    try:
        path = os.path.join(source_dir(source_id), name)
    except ValueError:
        return None
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_meta(source_id: str) -> dict | None:
    return _read(source_id, "meta.json")


def load_index(source_id: str) -> dict | None:
    return _read(source_id, "index.json")


def list_sources() -> list[dict]:
    out = []
    if not os.path.isdir(NOTES_ROOT):
        return out
    for sid in sorted(os.listdir(NOTES_ROOT)):
        if not _SID.match(sid):
            continue
        meta = load_meta(sid)
        if not meta:
            continue
        idx = load_index(sid)
        meta["indexed"] = bool(idx)
        meta["index_version"] = idx.get("version") if idx else 0
        meta["n_sections"] = len(idx.get("sections", [])) if idx else 0
        out.append(meta)
    return out


def log_usage(source_id: str, entry: dict) -> None:
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}
    with open(os.path.join(source_dir(source_id), "usage.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_usage(source_id: str) -> list[dict]:
    path = os.path.join(source_dir(source_id), "usage.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- 인덱스 생성


def build_index(source_id: str, *, provider_name: str | None = None,
                model: str | None = None, progress=None) -> dict:
    """원본 전체를 한 번 읽어 인덱스를 만든다. 비용이 드는 유일한 지점."""
    meta = load_meta(source_id)
    if not meta:
        raise FileNotFoundError(f"source {source_id} 없음")

    def report(msg, pct=None):
        if progress:
            progress(msg, pct)

    raw = source_dir(source_id, "raw")
    chunks: list[extract.Chunk] = []

    pages_json = _read_raw(source_id, "pages.json")
    if pages_json:
        pages = [extract.Page(page=p["page"], text=p["text"]) for p in pages_json]
        chunks += extract.chunk_pages(pages)

    transcript = ""
    tpath = os.path.join(raw, "transcript.txt")
    if os.path.exists(tpath):
        with open(tpath, encoding="utf-8") as f:
            transcript = f.read()
        chunks += extract.chunk_transcript(transcript)

    if not chunks:
        raise ValueError("원본에서 읽을 텍스트가 없습니다 (스캔 PDF 라면 OCR 이 먼저 필요합니다).")

    provider = get_provider(provider_name, model)
    ts_offsets = _transcript_offsets(transcript)
    from_pdf: list[dict] = []
    from_transcript: list[dict] = []
    tin = tout = 0

    for i, ch in enumerate(chunks, 1):
        report(f"인덱싱 {i}/{len(chunks)}", int(90 * i / len(chunks)))
        where = []
        if ch.pages:
            where.append(f"PDF {ch.pages[0]}~{ch.pages[-1]}쪽")
        if ch.time_start:
            where.append(f"전사 {ch.time_start}~{ch.time_end}")
        user = f"[원문 위치: {', '.join(where) or '미상'}]\n\n{ch.text}"

        res = provider.complete(INDEX_SYSTEM, user, json_mode=True, max_tokens=2000)
        tin += res.input_tokens
        tout += res.output_tokens
        try:
            parsed = parse_json(res.text)
        except (LLMError, json.JSONDecodeError) as exc:
            report(f"[경고] 조각 {i} 색인 실패: {exc}")
            continue

        for sec in parsed.get("sections") or []:
            if not isinstance(sec, dict) or not _slug(sec.get("title", "")):
                continue
            item = {
                "title": _slug(sec.get("title")),
                "concepts": _strlist(sec.get("concepts")),
                "formulas": _strlist(sec.get("formulas")),
                "examples": _strlist(sec.get("examples")),
                "summary": (sec.get("summary") or "").strip(),
                "pages": [],
                "time_start": "",
                "time_end": "",
                "char_span": [0, 0],
            }
            if ch.pages:
                # LLM 이 짚은 쪽수가 이 조각 안의 것일 때만 믿는다.
                page = sec.get("page")
                item["pages"] = [page] if isinstance(page, int) and page in ch.pages else list(ch.pages)
                from_pdf.append(item)
            else:
                ts = sec.get("time") if isinstance(sec.get("time"), str) else ""
                item["time_start"] = ts if ts in ts_offsets else ch.time_start
                item["time_end"] = ch.time_end
                item["char_span"] = [ts_offsets.get(item["time_start"], ch.char_span[0]),
                                     ch.char_span[1]]
                from_transcript.append(item)

    _tighten_spans(from_transcript, len(transcript))
    sections = _merge_sections(from_pdf, from_transcript)
    if not sections:
        raise LLMError("인덱스를 하나도 만들지 못했습니다. 프로바이더 응답을 확인하세요.")

    prev = load_index(source_id)
    index = {
        "schema": SCHEMA,
        "source_id": source_id,
        "title": meta["title"],
        "version": (prev.get("version", 0) + 1) if prev else 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "provider": {"name": provider.name, "model": provider.model},
        "sections": sections,
        "tokens": {"input": tin, "output": tout, "calls": len(chunks)},
    }
    _write(source_id, "index.json", index)
    log_usage(source_id, {
        "stage": "index", "provider": provider.name, "model": provider.model,
        "input_tokens": tin, "output_tokens": tout, "calls": len(chunks),
        "raw_chars": meta.get("raw_chars", 0), "index_version": index["version"],
    })
    report("인덱스 완료", 100)
    return index


def _strlist(v) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()][:20]


def _transcript_offsets(text: str) -> dict[str, int]:
    """`[HH:MM:SS]` 별 문자 오프셋. 섹션 단위 재조회의 좌표계가 된다."""
    out: dict[str, int] = {}
    pos = 0
    for line in text.splitlines(keepends=True):
        m = extract.TS.match(line.strip())
        if m and m.group(1) not in out:
            out[m.group(1)] = pos
        pos += len(line)
    return out


def _tighten_spans(sections: list[dict], total: int) -> None:
    """전사 섹션의 끝을 '다음 섹션 시작'으로 당긴다. 조각 전체가 아니라 그 절만 남는다."""
    ordered = sorted(sections, key=lambda s: s["char_span"][0])
    for cur, nxt in zip(ordered, ordered[1:]):
        if nxt["char_span"][0] > cur["char_span"][0]:
            cur["char_span"][1] = nxt["char_span"][0]
            cur["time_end"] = nxt["time_start"] or cur["time_end"]
    if ordered:
        ordered[-1]["char_span"][1] = max(ordered[-1]["char_span"][1], total)


def _merge_sections(from_pdf: list[dict], from_transcript: list[dict]) -> list[dict]:
    """같은 절을 가리키는 PDF 쪽·전사 쪽 항목을 하나로 합친다.

    강의자료와 전사는 같은 내용을 두 번 말한다. 합치지 않으면 인덱스가 두 배로
    부풀고, 정리본을 만들 때 같은 얘기가 두 번 들어간다. 합친 섹션은 PDF 쪽수와
    전사 타임코드를 **둘 다** 갖는다.
    """
    merged = [dict(s) for s in from_pdf]
    leftovers: list[dict] = []

    def absorb(dst: dict, src: dict) -> None:
        dst["concepts"] = _dedup(dst["concepts"], src["concepts"])
        dst["formulas"] = _dedup(dst["formulas"], src["formulas"])
        dst["examples"] = _dedup(dst["examples"], src["examples"])
        dst["time_start"] = dst["time_start"] or src["time_start"]
        dst["time_end"] = src["time_end"] or dst["time_end"]
        span = dst["char_span"]
        dst["char_span"] = [min(span[0], src["char_span"][0]) if span[1] else src["char_span"][0],
                            max(span[1], src["char_span"][1])]
        if src["summary"] and src["summary"] not in dst["summary"]:
            dst["summary"] = (dst["summary"] + " " + src["summary"]).strip()

    for t in from_transcript:
        hit = next((m for m in merged if _merge_key_match(m["title"], t["title"])), None)
        if hit is None:
            leftovers.append(t)
            continue
        absorb(hit, t)

    # 강의자료가 있으면 그 목차가 뼈대다. 강사가 지나가며 말한 "예제 9.4",
    # "시험 범위" 같은 토막은 별도의 절로 올리지 않고 시간상 직전 절에 흡수시킨다.
    # 안 그러면 인덱스가 토막으로 부풀어 정리본이 같은 얘기를 여러 번 한다.
    #
    # 단, 내용이 실린 절은 남긴다. 강의자료에 없고 강사만 다룬 내용을 통째로
    # 잃으면 나중에 "그 얘기 왜 빠졌냐"가 된다. 흡수해도 개념·수식·예제는
    # 부모 절에 그대로 들어가므로 내용 자체는 사라지지 않는다.
    if merged and leftovers:
        timed = sorted([m for m in merged if m["time_start"]], key=lambda m: m["time_start"])
        still: list[dict] = []
        for t in sorted(leftovers, key=lambda s: s["time_start"]):
            items = len(t["concepts"]) + len(t["formulas"]) + len(t["examples"])
            prev = [m for m in timed if m["time_start"] <= t["time_start"]]
            if prev and items <= FRAGMENT_ITEMS:
                absorb(prev[-1], t)
            else:
                still.append(t)
                # 살아남은 절도 이후 토막의 흡수 대상이 된다 (시간순으로 직전이므로)
                timed.append(t)
                timed.sort(key=lambda m: m["time_start"])
        leftovers = still

    out = merged + leftovers
    for i, sec in enumerate(out, 1):
        sec["id"] = f"s{i:02d}"
    # 키 순서를 고정해 읽기 좋게 둔다
    order = ("id", "title", "concepts", "formulas", "examples", "summary",
             "pages", "time_start", "time_end", "char_span")
    return [{k: sec[k] for k in order} for sec in out]


def _read_raw(source_id: str, name: str):
    path = os.path.join(source_dir(source_id, "raw"), name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 선택적 재조회


def load_raw_sections(source_id: str, section_ids: list[str]) -> str:
    """지정한 섹션에 해당하는 원본 구간만 꺼낸다.

    "3장 예제만" 같은 요청에서 쓴다. 전체 원본이 아니라 해당 챕터 분량만
    들어가므로 보통 전체의 1/10 이하다.
    """
    index = load_index(source_id)
    if not index:
        return ""
    wanted = {s["id"]: s for s in index["sections"] if s["id"] in set(section_ids)}
    if not wanted:
        return ""

    pages_json = _read_raw(source_id, "pages.json") or []
    page_text = {p["page"]: p["text"] for p in pages_json}

    transcript = ""
    tpath = os.path.join(source_dir(source_id, "raw"), "transcript.txt")
    if os.path.exists(tpath):
        with open(tpath, encoding="utf-8") as f:
            transcript = f.read()

    out: list[str] = []
    for sec in wanted.values():
        out.append(f"── [{sec['id']}] {sec['title']} 원문 ──")
        for p in sec.get("pages") or []:
            if page_text.get(p):
                out.append(f"[p.{p}]\n{page_text[p]}")
        span = sec.get("char_span") or [0, 0]
        if transcript and span[1] > span[0]:
            out.append(transcript[span[0]:span[1]].strip())
    return "\n\n".join(out).strip()
