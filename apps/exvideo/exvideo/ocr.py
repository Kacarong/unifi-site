"""슬라이드 이미지에서 한국어/영어 텍스트를 OCR로 추출한다 (easyocr)."""

_reader = None


def _get_reader(gpu: bool = True):
    global _reader
    if _reader is None:
        import easyocr  # 지연 임포트
        _reader = easyocr.Reader(["ko", "en"], gpu=gpu)
    return _reader


def ocr_image(image_path: str, gpu: bool = True):
    """반환: (text, boxes) — text는 줄바꿈으로 합친 문자열, boxes는 [ [x1,y1,x2,y2], ... ]"""
    reader = _get_reader(gpu=gpu)
    results = reader.readtext(image_path, detail=1, paragraph=False)
    lines = []
    boxes = []
    for box, txt, conf in results:
        if not txt or conf < 0.3:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append([int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))])
        lines.append(txt.strip())
    return "\n".join(lines), boxes
