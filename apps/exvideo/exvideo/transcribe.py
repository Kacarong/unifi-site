"""faster-whisper로 영상의 음성을 타임스탬프 포함 전사한다 (로컬, GPU 자동)."""


def transcribe(video_path: str, model_size: str = "large-v3", language: str = "ko",
               device: str = "auto", compute_type: str = "auto"):
    """반환: [{start, end, text}]"""
    from faster_whisper import WhisperModel  # 지연 임포트

    if device == "auto":
        try:
            import torch  # noqa
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"

    print(f"[전사] Whisper 모델 로딩 (size={model_size}, device={device}, compute={compute_type}) ...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(video_path, language=language, vad_filter=True)

    out = []
    for seg in segments:
        out.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()})
        print(f"  [{int(seg.start)//60:02d}:{int(seg.start)%60:02d}] {seg.text.strip()[:60]}")
    return out
