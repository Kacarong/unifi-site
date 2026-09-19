"""전사 + 슬라이드(OCR) + 그림을 시간순으로 합쳐 붙여넣기용 프롬프트 묶음을 만든다."""
import os


def _fmt(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


PROMPT_HEADER = """아래는 강의 영상에서 자동 추출한 자료입니다(음성 전사 + 슬라이드 텍스트 + 슬라이드/그림 이미지 목록).
이 내용을 바탕으로 아래 '요청'대로 학습용 자료로 정리해 주세요.

[요청] (여기에 원하는 구성/분량/디자인을 적으세요. 예: 목차 → 핵심요약 → 개념정리 → 예상문제, 표로 정리 등)

[참고]
- 시간표시는 [HH:MM:SS] 형식입니다.
- "슬라이드 N" 아래 텍스트는 화면에 표시된 내용(OCR)이며, 관련 그림 파일 경로가 함께 표시됩니다.
- 그림/도표가 중요하면 해당 이미지 파일을 함께 첨부해 참고하세요.

────────────────────────────────────────
"""


def build_bundle(out_dir: str, transcript, slides, rel_root: str = "."):
    """transcript: [{start,end,text}], slides: [{index,time,ts,path,ocr_text,figures[]}]"""
    lines = [PROMPT_HEADER]
    slides = sorted(slides, key=lambda s: s["time"])
    segs = sorted(transcript, key=lambda s: s["start"]) if transcript else []
    si = 0

    def emit_segments(until):
        nonlocal si
        while si < len(segs) and (until is None or segs[si]["start"] < until):
            s = segs[si]
            lines.append(f"[{_fmt(s['start'])}] {s['text']}")
            si += 1

    # 첫 슬라이드 이전(도입부) 전사
    if slides:
        emit_segments(slides[0]["time"])
    else:
        emit_segments(None)

    for i, sl in enumerate(slides):
        nxt = slides[i + 1]["time"] if i + 1 < len(slides) else None
        lines.append("")
        lines.append(f"■ 슬라이드 {sl['index']} [{sl['ts']}]  (이미지: {os.path.relpath(sl['path'], out_dir)})")
        ocr = (sl.get("ocr_text") or "").strip()
        if ocr:
            lines.append("  [슬라이드 텍스트]")
            for ln in ocr.splitlines():
                if ln.strip():
                    lines.append(f"    {ln.strip()}")
        figs = sl.get("figures") or []
        if figs:
            lines.append("  [그림/도표]")
            for f in figs:
                lines.append(f"    - {os.path.relpath(f, out_dir)}")
        lines.append("  [해당 구간 설명(음성)]")
        emit_segments(nxt)

    # 마지막 슬라이드 이후 전사
    emit_segments(None)

    bundle_path = os.path.join(out_dir, "bundle.md")
    with open(bundle_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # 순수 전사본도 별도 저장
    tpath = os.path.join(out_dir, "transcript.txt")
    with open(tpath, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"[{_fmt(s['start'])}] {s['text']}\n")

    return bundle_path
