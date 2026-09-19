"""영상에서 슬라이드(장면 전환) 키프레임을 추출하고 중복을 제거한다."""
import os


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def extract_slides(video_path: str, out_dir: str, sample_interval: float = 1.0,
                   diff_threshold: float = 8.0, phash_distance: int = 6):
    """
    sample_interval: 몇 초 간격으로 프레임을 검사할지
    diff_threshold: 직전 유지 슬라이드와의 평균 밝기차(0~255) 임계값 (클수록 둔감)
    phash_distance: perceptual hash 해밍거리 임계값 (작을수록 엄격한 중복제거)
    반환: [{index, time, ts, path}]
    """
    import cv2
    import imagehash
    from PIL import Image

    slides_dir = os.path.join(out_dir, "slides")
    os.makedirs(slides_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(fps * sample_interval)))

    slides = []
    last_small = None
    last_hashes = []
    idx = 0
    frame_no = 0

    while True:
        ret = cap.grab()
        if not ret:
            break
        if frame_no % step == 0:
            ok, frame = cap.retrieve()
            if ok and frame is not None:
                small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90))
                is_new = last_small is None
                if last_small is not None:
                    diff = float(cv2.absdiff(small, last_small).mean())
                    if diff >= diff_threshold:
                        is_new = True
                if is_new:
                    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    ph = imagehash.phash(pil)
                    # 이전에 나온 슬라이드와 거의 동일하면 건너뜀(중복 제거)
                    if any((ph - h) <= phash_distance for h in last_hashes):
                        last_small = small
                        frame_no += 1
                        continue
                    idx += 1
                    t = frame_no / fps
                    path = os.path.join(slides_dir, f"slide_{idx:03d}.png")
                    cv2.imwrite(path, frame)
                    slides.append({"index": idx, "time": t, "ts": _fmt_ts(t), "path": path})
                    last_hashes.append(ph)
                    last_small = small
                else:
                    last_small = small
        frame_no += 1

    cap.release()
    return slides
