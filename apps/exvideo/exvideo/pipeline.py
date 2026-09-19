"""재사용 가능한 처리 파이프라인. CLI와 웹 백엔드가 공통으로 사용한다.

progress(msg: str, pct: int|None) 콜백으로 진행상황을 알린다.
"""
import os


def run_pipeline(source, out_dir, *, model="large-v3", lang="ko",
                 sample_interval=1.0, diff_threshold=8.0,
                 do_transcribe=True, do_ocr=True, do_figures=True,
                 cpu=False, progress=None):
    def report(msg, pct=None):
        if progress:
            progress(msg, pct)
        else:
            print(msg)

    os.makedirs(out_dir, exist_ok=True)

    # 1) 입력 해석
    from .download import resolve_input
    report("입력 확인/다운로드 중...", 5)
    video = resolve_input(source, out_dir)

    # 2) 전사
    transcript = []
    if do_transcribe:
        report("음성 전사(Whisper) 중... (첫 실행은 모델 다운로드로 오래 걸릴 수 있어요)", 15)
        from .transcribe import transcribe
        transcript = transcribe(video, model_size=model, language=lang,
                                device="cpu" if cpu else "auto")
    else:
        report("전사 생략", 15)

    # 3) 슬라이드 추출
    report("슬라이드 키프레임 추출/중복제거 중...", 55)
    from .slides import extract_slides
    slides = extract_slides(video, out_dir, sample_interval=sample_interval,
                            diff_threshold=diff_threshold)
    report(f"고유 슬라이드 {len(slides)}개", 65)

    # 4) OCR + 그림 크롭
    gpu = not cpu
    for i, sl in enumerate(slides, 1):
        boxes = []
        if do_ocr:
            try:
                from .ocr import ocr_image
                sl["ocr_text"], boxes = ocr_image(sl["path"], gpu=gpu)
            except Exception as e:
                report(f"[OCR 경고] {os.path.basename(sl['path'])}: {e}")
                sl["ocr_text"] = ""
        else:
            sl["ocr_text"] = ""
        if do_figures:
            try:
                from .figures import extract_figures
                sl["figures"] = extract_figures(sl["path"], out_dir, text_boxes=boxes)
            except Exception as e:
                report(f"[그림 경고] {os.path.basename(sl['path'])}: {e}")
                sl["figures"] = []
        else:
            sl["figures"] = []
        pct = 65 + int(30 * i / max(1, len(slides)))
        report(f"슬라이드 {sl['index']} 처리 · 그림 {len(sl.get('figures', []))}개", pct)

    # 5) 번들 생성
    report("프롬프트 묶음(bundle.md) 생성 중...", 97)
    from .bundle import build_bundle
    bundle_path = build_bundle(out_dir, transcript, slides)

    report("완료", 100)
    return {
        "bundle": bundle_path,
        "slides_dir": os.path.join(out_dir, "slides"),
        "figures_dir": os.path.join(out_dir, "figures"),
        "transcript": os.path.join(out_dir, "transcript.txt"),
        "n_slides": len(slides),
    }
