"""슬라이드 이미지에서 '그림/도표 영역'만 찾아 크롭해 저장한다.

휴리스틱: 배경색과 다른 전경 영역 중, OCR로 잡힌 '텍스트 영역'을 제외한
큰 덩어리를 그림 후보로 보고 잘라낸다. 슬라이드 디자인에 따라 정확도는 달라질 수 있다.
"""
import os


def _merge_boxes(boxes, iou_gap=10):
    """겹치거나 매우 가까운 박스를 병합."""
    merged = True
    boxes = [list(b) for b in boxes]
    while merged:
        merged = False
        out = []
        while boxes:
            a = boxes.pop()
            joined = False
            for b in out:
                if (a[0] <= b[2] + iou_gap and b[0] <= a[2] + iou_gap and
                        a[1] <= b[3] + iou_gap and b[1] <= a[3] + iou_gap):
                    b[0] = min(a[0], b[0]); b[1] = min(a[1], b[1])
                    b[2] = max(a[2], b[2]); b[3] = max(a[3], b[3])
                    joined = True
                    merged = True
                    break
            if not joined:
                out.append(a)
        boxes = out
    return boxes


def extract_figures(image_path, out_dir, text_boxes=None, min_area_ratio=0.02,
                    max_area_ratio=0.9, pad=8):
    """반환: 저장한 그림 이미지 경로 리스트."""
    import cv2
    import numpy as np

    figures_dir = os.path.join(out_dir, "figures")
    os.makedirs(figures_dir, exist_ok=True)

    img = cv2.imread(image_path)
    if img is None:
        return []
    h, w = img.shape[:2]
    area = h * w

    # 배경색 추정: 테두리 픽셀의 중앙값
    border = np.concatenate([
        img[0:5, :, :].reshape(-1, 3), img[h - 5:h, :, :].reshape(-1, 3),
        img[:, 0:5, :].reshape(-1, 3), img[:, w - 5:w, :].reshape(-1, 3),
    ], axis=0)
    bg = np.median(border, axis=0)

    # 전경 마스크: 배경과 색 차이가 큰 픽셀
    dist = np.abs(img.astype(np.int16) - bg.astype(np.int16)).sum(axis=2)
    fg = (dist > 40).astype(np.uint8) * 255

    # 텍스트 영역 제거
    if text_boxes:
        for (x1, y1, x2, y2) in text_boxes:
            x1 = max(0, x1 - 3); y1 = max(0, y1 - 3)
            x2 = min(w, x2 + 3); y2 = min(h, y2 + 3)
            fg[y1:y2, x1:x2] = 0

    # 그림 덩어리 연결
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cand = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        a = cw * ch
        if a < area * min_area_ratio or a > area * max_area_ratio:
            continue
        if cw < 40 or ch < 40:
            continue
        cand.append([x, y, x + cw, y + ch])

    cand = _merge_boxes(cand)
    # 너무 작은 것 재필터 + 면적 큰 순 정렬
    cand = [b for b in cand if (b[2] - b[0]) * (b[3] - b[1]) >= area * min_area_ratio]
    cand.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)

    paths = []
    base = os.path.splitext(os.path.basename(image_path))[0]
    for i, (x1, y1, x2, y2) in enumerate(cand, 1):
        x1 = max(0, x1 - pad); y1 = max(0, y1 - pad)
        x2 = min(w, x2 + pad); y2 = min(h, y2 + pad)
        crop = img[y1:y2, x1:x2]
        p = os.path.join(figures_dir, f"{base}_fig_{i}.png")
        cv2.imwrite(p, crop)
        paths.append(p)
    return paths
