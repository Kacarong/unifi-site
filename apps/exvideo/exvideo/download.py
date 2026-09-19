"""입력 소스 해석: 로컬 파일 경로 / 구글드라이브 공유 링크 / 일반 URL → 로컬 파일."""
import os
import re
import urllib.request


def _gdrive_id(url: str):
    # https://drive.google.com/file/d/<ID>/view  또는 ?id=<ID>
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url)
    if m:
        return m.group(1)
    return None


def resolve_input(src: str, out_dir: str) -> str:
    """src가 로컬 파일이면 그대로, 링크면 내려받아 로컬 경로를 반환."""
    if os.path.exists(src):
        return src

    os.makedirs(out_dir, exist_ok=True)

    if "drive.google.com" in src:
        gid = _gdrive_id(src)
        if not gid:
            raise ValueError("구글드라이브 링크에서 파일 ID를 찾지 못했습니다. 공유 링크를 확인하세요.")
        import gdown  # 지연 임포트
        dest = os.path.join(out_dir, "source_video.mp4")
        print(f"[다운로드] 구글드라이브에서 내려받는 중 (id={gid}) ...")
        gdown.download(id=gid, output=dest, quiet=False)
        return dest

    if src.startswith("http://") or src.startswith("https://"):
        dest = os.path.join(out_dir, "source_video" + os.path.splitext(src)[1] or ".mp4")
        print(f"[다운로드] URL에서 내려받는 중 ...")
        urllib.request.urlretrieve(src, dest)
        return dest

    raise FileNotFoundError(f"입력을 찾을 수 없습니다: {src}")
