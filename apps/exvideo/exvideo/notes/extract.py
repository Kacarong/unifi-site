"""원본 읽기 — 여기에는 LLM 이 없다.

"PDF 읽는 데 무료 LLM 쓸 수 있나"의 답: PDF 텍스트 추출에는 LLM 이 아예
필요 없다. PyMuPDF 가 글자를 그대로 꺼낸다. 토큰 0, 비용 0, 오독 0.
LLM 은 그 다음 단계(정리)에서만 쓴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Page:
    page: int  # 1-based
    text: str


@dataclass
class Chunk:
    """LLM 한 번에 태울 원본 조각. 원본으로 되돌아갈 참조를 들고 있다."""

    text: str
    pages: list[int] = field(default_factory=list)
    time_start: str = ""
    time_end: str = ""
    char_span: tuple[int, int] = (0, 0)  # 전사 원문 내 문자 오프셋


def pdf_pages(path: str) -> list[Page]:
    import pymupdf

    out: list[Page] = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc, 1):
            out.append(Page(page=i, text=page.get_text("text").strip()))
    return out


def pdf_is_scanned(pages: list[Page], min_chars: int = 40) -> bool:
    """글자가 거의 안 나오면 스캔본이다 — 이때만 OCR 이 필요하다."""
    if not pages:
        return True
    filled = sum(1 for p in pages if len(p.text) >= min_chars)
    return filled < max(1, len(pages) // 4)


def chunk_pages(pages: list[Page], target_chars: int = 2500) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[str] = []
    nums: list[int] = []
    size = 0
    for p in pages:
        if not p.text:
            continue
        piece = f"[p.{p.page}]\n{p.text}"
        if size and size + len(piece) > target_chars:
            chunks.append(Chunk(text="\n\n".join(buf), pages=list(nums)))
            buf, nums, size = [], [], 0
        buf.append(piece)
        nums.append(p.page)
        size += len(piece)
    if buf:
        chunks.append(Chunk(text="\n\n".join(buf), pages=list(nums)))
    return chunks


TS = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$")


def chunk_transcript(text: str, target_chars: int = 2500) -> list[Chunk]:
    """`[HH:MM:SS] 내용` 줄 단위 전사를 자른다.

    char_span 은 원본 문자열 기준 오프셋이라 나중에 이 구간만 다시 꺼내 쓸 수 있다.
    """
    chunks: list[Chunk] = []
    buf: list[str] = []
    start_ts = end_ts = ""
    begin = 0
    pos = 0
    size = 0
    for line in text.splitlines(keepends=True):
        m = TS.match(line.strip())
        ts = m.group(1) if m else ""
        if size and size + len(line) > target_chars:
            chunks.append(Chunk(text="".join(buf).strip(), time_start=start_ts,
                                time_end=end_ts, char_span=(begin, pos)))
            buf, size, begin, start_ts = [], 0, pos, ts
        if not buf:
            begin = pos
            start_ts = ts or start_ts
        if ts:
            end_ts = ts
        buf.append(line)
        size += len(line)
        pos += len(line)
    if buf and "".join(buf).strip():
        chunks.append(Chunk(text="".join(buf).strip(), time_start=start_ts,
                            time_end=end_ts, char_span=(begin, pos)))
    return chunks
