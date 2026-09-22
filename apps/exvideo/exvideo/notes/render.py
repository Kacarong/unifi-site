"""인덱스 → 요청한 구성의 요약정리본 → 한글 PDF.

입력은 **인덱스만** 이다. 원본 전사와 강의자료 PDF 는 여기서 읽지 않는다.
예외는 하나: 사용자가 특정 섹션을 콕 집어 "원문까지 보고 만들어라"고 한 경우
(`raw_sections`)에만 그 섹션 구간을 덧붙인다.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import uuid

from . import index as idx
from .llm import LLMError, get_provider

# 구성 조각 — 사용자가 고르는 단위
PARTS = {
    "toc": ("목차", "전체 목차를 계층 구조로. 각 항목 옆에 PDF 쪽수와 타임코드를 괄호로 표기."),
    "summary": ("핵심요약", "강의 전체의 핵심을 10줄 이내로. 무엇을 배우는 시간인지가 드러나게."),
    "concepts": ("개념정리", "핵심 개념을 용어 → 정의 → 왜 중요한지 순서로. 용어는 인덱스 표기 그대로."),
    "formulas": ("수식정리", "수식을 인덱스에 적힌 그대로 옮기고, 각 기호가 무엇인지와 언제 쓰는지 한 줄씩."),
    "examples": ("예제정리", "인덱스의 예제를 문제 → 접근 → 답 순서로. 예제가 없는 섹션은 건너뛴다."),
    "quiz": ("예상문제", "인덱스에 실제로 있는 내용만으로 예상문제 8개와 정답·해설. 없는 내용으로 문제를 만들지 않는다."),
}

SYSTEM = """당신은 한국어 학습자료 편집자입니다.

받는 것은 강의의 '구조 보존 인덱스'입니다. 원본 전사와 강의자료 PDF 는 주어지지
않습니다. 인덱스에 있는 내용만으로 작성하세요.

절대 규칙:
- 인덱스에 없는 사실을 지어내지 않습니다. 근거가 부족하면 그 항목을 비우고
  "(인덱스에 해당 내용 없음)" 이라고 적습니다.
- 용어·수식·예제는 인덱스 표기를 그대로 씁니다.
- 출력은 마크다운입니다. `#` `##` `###` 제목, `-` 목록, `1.` 번호목록,
  `**강조**` 만 씁니다. 표와 코드펜스는 쓰지 않습니다.
- 전체를 코드펜스로 감싸지 않습니다. 마크다운 본문만 바로 출력합니다.
- 수식은 LaTeX 로 쓰지 않습니다. 인덱스에 적힌 평문 표기를 그대로 씁니다.
  (`\\frac{a}{b}` 가 아니라 `a/b`, `\\lim_{x \\to a}` 가 아니라 `lim_{x->a}`)
- 목록 항목 안에 `#` 제목 표시를 또 넣지 않습니다.
- 한국어로 씁니다."""


LANG_LOCK = """

[다시 지시] 앞선 출력이 한국어를 벗어났습니다. 이번에는 처음부터 끝까지
한국어로만 쓰십시오. 중국어 한자와 중국어 문장을 한 글자도 쓰지 마십시오.
수학 기호와 영문 약어는 그대로 써도 됩니다."""

# 한글 대비 중국어 한자 비율이 이 값을 넘으면 언어가 샜다고 본다.
# 한국어 글에 한자가 조금 섞이는 건 정상이라 0 으로 두지 않는다.
DRIFT_LIMIT = 0.05


def _foreign_ratio(text: str) -> float:
    """중국어 한자 / (한글 + 중국어 한자). 0 이면 순수 한국어."""
    hangul = sum(1 for c in text if "가" <= c <= "힣")
    han = sum(1 for c in text if "一" <= c <= "鿿")
    return han / (hangul + han) if (hangul + han) else 0.0


def _index_payload(index: dict, section_ids: list[str] | None) -> str:
    """LLM 에 실제로 들어가는 인덱스 본문. 이게 입력 토큰의 거의 전부다."""
    secs = index["sections"]
    if section_ids:
        keep = set(section_ids)
        secs = [s for s in secs if s["id"] in keep]
    lines = [f"# 강의: {index['title']} (인덱스 v{index['version']})"]
    for s in secs:
        where = []
        if s.get("pages"):
            where.append(f"p.{s['pages'][0]}-{s['pages'][-1]}")
        if s.get("time_start"):
            where.append(f"{s['time_start']}~{s['time_end']}")
        lines.append(f"\n## [{s['id']}] {s['title']}  ({', '.join(where) or '위치미상'})")
        if s.get("summary"):
            lines.append(s["summary"])
        for label, key in (("개념", "concepts"), ("수식", "formulas"), ("예제", "examples")):
            for item in s.get(key) or []:
                lines.append(f"- {label}: {item}")
    return "\n".join(lines)


def build_prompt(index: dict, *, parts: list[str], section_ids: list[str] | None = None,
                 note: str = "", raw_text: str = "") -> str:
    chosen = [p for p in parts if p in PARTS] or ["summary"]
    wanted = "\n".join(f"{i}. **{PARTS[p][0]}** — {PARTS[p][1]}" for i, p in enumerate(chosen, 1))
    blocks = [
        "[요청하는 구성] 아래 순서 그대로, 각 항목을 `##` 제목으로 시작하세요.",
        wanted,
    ]
    if note.strip():
        blocks.append(f"[추가 요청]\n{note.strip()}")
    blocks.append("[강의 인덱스]\n" + _index_payload(index, section_ids))
    if raw_text:
        blocks.append(
            "[선택 섹션 원문] — 아래 섹션만 원문을 함께 제공합니다. 나머지는 인덱스만 보고 쓰세요.\n"
            + raw_text
        )
    return "\n\n".join(blocks)


def generate(source_id: str, *, parts: list[str], section_ids: list[str] | None = None,
             note: str = "", raw_sections: list[str] | None = None,
             provider_name: str | None = None, model: str | None = None,
             max_tokens: int = 0, progress=None) -> dict:
    index = idx.load_index(source_id)
    if not index:
        raise FileNotFoundError("인덱스가 아직 없습니다. 먼저 인덱스를 만드세요.")

    def report(msg, pct=None):
        if progress:
            progress(msg, pct)

    raw_text = idx.load_raw_sections(source_id, raw_sections) if raw_sections else ""
    prompt = build_prompt(index, parts=parts, section_ids=section_ids, note=note, raw_text=raw_text)

    provider = get_provider(provider_name, model)
    budget = max_tokens or max(2000, 1200 * max(1, len(parts)))
    report(f"{provider.name}/{provider.model} 로 정리본 생성 중…", 20)
    res = provider.complete(SYSTEM, prompt, max_tokens=budget)

    # 작은 중국어권 모델(qwen2.5 등)은 근거가 약한 생성 과제 — 특히 '예상문제' —
    # 에서 중국어로 샌다. 실측: 목차·요약·개념정리는 한국어를 지켰지만 예상문제는
    # 한자 비율 97% 로 무너졌고, 같은 모델로 더 세게 지시해 다시 시켜도 96% 였다.
    # 같은 모델 재시도는 시간만 버리므로, 대체 프로바이더가 지정돼 있을 때만
    # 거기로 넘긴다. 없으면 결과에 표시만 남겨 사용자가 알 수 있게 한다.
    drift = _foreign_ratio(res.text)
    fallback = os.environ.get("EXVIDEO_LLM_FALLBACK", "").strip()
    if drift > DRIFT_LIMIT and fallback and fallback != provider.name:
        report(f"한국어 이탈({drift:.0%}) — {fallback} 로 다시 생성합니다", 50)
        try:
            alt = get_provider(fallback)
            alt_res = alt.complete(SYSTEM + LANG_LOCK, prompt, max_tokens=budget)
            if _foreign_ratio(alt_res.text) < drift:
                provider, res, drift = alt, alt_res, _foreign_ratio(alt_res.text)
        except LLMError as exc:
            report(f"대체 프로바이더 실패: {exc}")
    elif drift > DRIFT_LIMIT:
        report(f"[경고] 한국어 이탈 {drift:.0%} — 이 구성은 더 큰 모델이 필요합니다"
               " (EXVIDEO_LLM_FALLBACK 에 claude/gemini 지정)", 50)

    if res.chunks > 1:
        report(f"[경고] 답변이 {res.chunks}조각으로 나뉘어 이어졌습니다 — 이은 자리에서"
               " 몇 줄이 빠졌을 수 있습니다. 구성을 나눠서 만드는 편이 안전합니다.", 70)

    render_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    out_dir = idx.source_dir(source_id, "outputs")
    md_path = os.path.join(out_dir, f"{render_id}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(res.text)

    report("PDF 조판 중…", 80)
    pdf_path = os.path.join(out_dir, f"{render_id}.pdf")
    subtitle = " · ".join(PARTS[p][0] for p in parts if p in PARTS)
    write_pdf(res.text, pdf_path, title=index["title"], subtitle=subtitle)

    usage = {
        "stage": "render", "render_id": render_id,
        "provider": provider.name, "model": provider.model,
        "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
        "index_version": index["version"], "parts": parts,
        "used_raw_sections": raw_sections or [],
        "prompt_chars": len(prompt),
        # 0 이 아니면 모델이 한국어를 벗어난 것 — 유료 모델로 바꿀 근거가 된다
        "foreign_ratio": round(drift, 3),
        # 1 보다 크면 답변이 잘려 이어 쓴 것 — 이은 자리가 성글 수 있다
        "chunks": res.chunks,
    }
    idx.log_usage(source_id, usage)

    meta = {"render_id": render_id, "pdf": pdf_path, "markdown": md_path, **usage}
    with open(os.path.join(out_dir, f"{render_id}.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    report("완료", 100)
    return meta


def list_outputs(source_id: str) -> list[dict]:
    out_dir = idx.source_dir(source_id, "outputs")
    items = []
    for name in sorted(os.listdir(out_dir), reverse=True):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(out_dir, name), encoding="utf-8") as f:
            items.append(json.load(f))
    return items


# ---------------------------------------------------------------- 한글 PDF 조판

FONT_CANDIDATES = [
    ("NanumGothic", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
     "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ("NotoSansKR", "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.ttf"),
]

_registered: str | None = None


def _register_font() -> str:
    """한글 TTF 를 reportlab 에 등록한다. 없으면 바로 실패 — 네모박스 PDF 를 만들지 않는다."""
    global _registered
    if _registered:
        return _registered

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.fonts import addMapping

    env_reg = os.environ.get("EXVIDEO_PDF_FONT")
    candidates = list(FONT_CANDIDATES)
    if env_reg:
        candidates.insert(0, ("UserFont", env_reg, os.environ.get("EXVIDEO_PDF_FONT_BOLD", env_reg)))

    for name, regular, bold in candidates:
        if not os.path.exists(regular):
            continue
        pdfmetrics.registerFont(TTFont(name, regular))
        bold_name = name
        if os.path.exists(bold) and bold != regular:
            bold_name = f"{name}-Bold"
            pdfmetrics.registerFont(TTFont(bold_name, bold))
        addMapping(name, 0, 0, name)
        addMapping(name, 1, 0, bold_name)
        addMapping(name, 0, 1, name)
        addMapping(name, 1, 1, bold_name)
        _registered = name
        return name

    raise RuntimeError(
        "한글 TTF 글꼴을 찾지 못했습니다. NanumGothic 을 설치하거나 "
        "EXVIDEO_PDF_FONT 에 TTF 경로를 지정하세요."
    )


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_CODE = re.compile(r"`([^`]+)`")

# LLM 은 지시해도 LaTeX 와 코드펜스를 섞어 내보낸다. 조판 직전에 걷어낸다.
# 여기서 안 걷으면 PDF 에 \( \frac{a}{b} \) 같은 게 글자 그대로 찍힌다.
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*$")
_LIST_HEAD = re.compile(r"^([-*+]|\d+[.)])\s+#{1,6}\s*")
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_LATEX_CMD = re.compile(r"\\(?:left|right|displaystyle|,|;|!|quad|qquad)\b|\\[,;!]")
_MATH_DELIM = re.compile(r"\\[()\[\]]")
_LATEX_WORD = {
    r"\to": "->", r"\rightarrow": "->", r"\infty": "inf", r"\cdot": "·",
    r"\times": "×", r"\le": "<=", r"\ge": ">=", r"\neq": "!=", r"\pm": "±",
    r"\lim": "lim", r"\int": "integral", r"\sum": "sum", r"\sqrt": "sqrt",
    r"\sin": "sin", r"\cos": "cos", r"\tan": "tan", r"\ln": "ln", r"\log": "log",
    r"\alpha": "a", r"\beta": "b", r"\theta": "θ", r"\pi": "pi",
    r"\epsilon": "e", r"\varepsilon": "e", r"\delta": "d", r"\Delta": "Δ",
}


def _delatex(text: str) -> str:
    text = _MATH_DELIM.sub("", text)
    text = _LATEX_CMD.sub("", text)
    for _ in range(3):  # 중첩 분수
        new = _FRAC.sub(r"(\1)/(\2)", text)
        if new == text:
            break
        text = new
    for src, dst in _LATEX_WORD.items():
        text = text.replace(src, dst)
    return text


def normalize_markdown(text: str) -> str:
    """조판 전 정리 — 모델이 흘린 코드펜스·중복 제목표시·LaTeX 를 걷어낸다."""
    lines = [ln for ln in text.splitlines() if not _FENCE.match(ln)]
    out = []
    for ln in lines:
        # "1. ## [s01] 1장" 처럼 목록 안에 제목 표시가 또 들어온 경우
        ln = _LIST_HEAD.sub(r"\1 ", ln)
        out.append(_delatex(ln))
    return "\n".join(out)


def _inline(text: str) -> str:
    out = html.escape(text)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _CODE.sub(r"<font face='Courier'>\1</font>", out)
    out = _ITALIC.sub(r"<i>\1</i>", out)
    return out


def write_pdf(markdown: str, path: str, *, title: str = "", subtitle: str = "") -> str:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (ListFlowable, ListItem, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer)

    font = _register_font()

    def style(name, size, **kw):
        return ParagraphStyle(name, fontName=font, fontSize=size, leading=size * 1.55,
                              alignment=TA_LEFT, **kw)

    s_title = style("t", 21, spaceAfter=4)
    s_sub = style("st", 10.5, textColor="#6b7280", spaceAfter=18)
    s_h1 = style("h1", 16.5, spaceBefore=16, spaceAfter=7)
    s_h2 = style("h2", 13.5, spaceBefore=13, spaceAfter=5)
    s_h3 = style("h3", 11.5, spaceBefore=10, spaceAfter=4)
    s_body = style("b", 10.5, spaceAfter=5)
    s_li = style("li", 10.5, spaceAfter=2)

    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=title or "요약정리본", author="unifi-site · ex-video",
    )

    flow = []
    if title:
        flow.append(Paragraph(_inline(title), s_title))
    stamp = time.strftime("%Y-%m-%d %H:%M")
    flow.append(Paragraph(_inline(" · ".join(x for x in (subtitle, stamp) if x)), s_sub))

    markdown = normalize_markdown(markdown)
    bullets: list[str] = []
    numbered: list[str] = []

    def flush():
        nonlocal bullets, numbered
        for items, kind, start in ((bullets, "bullet", None), (numbered, "1", 1)):
            if not items:
                continue
            kw = {"bulletType": kind, "leftIndent": 14}
            if start:
                kw["start"] = start
            flow.append(ListFlowable(
                [ListItem(Paragraph(_inline(i), s_li), leftIndent=14) for i in items], **kw))
            flow.append(Spacer(1, 4))
        bullets, numbered = [], []

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped in ("---", "***", "___"):
            flush()
            flow.append(PageBreak())
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush()
            level = len(m.group(1))
            flow.append(Paragraph(_inline(m.group(2)), (s_h1, s_h2, s_h3)[min(level, 3) - 1]))
            continue
        m = re.match(r"^[-*+]\s+(.*)$", stripped)
        if m:
            if numbered:
                flush()
            bullets.append(m.group(1))
            continue
        m = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if m:
            if bullets:
                flush()
            numbered.append(m.group(1))
            continue
        flush()
        flow.append(Paragraph(_inline(stripped), s_body))

    flush()
    if len(flow) <= 2:
        flow.append(Paragraph("(생성된 내용이 없습니다)", s_body))

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColorRGB(0.45, 0.47, 0.52)
        canvas.drawRightString(A4[0] - 20 * mm, 11 * mm, str(canvas.getPageNumber()))
        canvas.restoreState()

    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    return path
