"""입력 소스 해석: 로컬 파일 경로 / 구글드라이브 공유 링크 / 그 외 링크 → 로컬 파일."""
import glob
import os
import re

# 내려받을 영상의 세로 해상도 상한
MAX_HEIGHT = int(os.environ.get("EXVIDEO_MAX_HEIGHT", "720"))

# 이보다 작으면 영상이 아니라 오류 페이지로 본다. 가장 짧은 강의도 이보다는 크다.
MIN_MEDIA_BYTES = 64 * 1024


def _gdrive_id(url: str):
    # https://drive.google.com/file/d/<ID>/view  또는 ?id=<ID>
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url)
    if m:
        return m.group(1)
    return None


def _download_link(src: str, out_dir: str) -> str:
    """유튜브를 비롯한 일반 링크를 yt-dlp 로 내려받는다.

    예전에는 링크를 그대로 urlretrieve 했다. 유튜브 주소를 넣으면 영상이 아니라
    **재생 페이지 HTML** 이 `source_video.mp4` 라는 이름으로 저장됐고, 전사 단계에
    가서야 알 수 없는 오류로 터졌다. yt-dlp 는 유튜브뿐 아니라 직접 링크(.mp4)와
    HLS(.m3u8)도 같은 방식으로 처리하므로 경로를 하나로 합쳤다.
    """
    try:
        import yt_dlp  # 지연 임포트
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp 가 필요합니다. `pip install -r apps/exvideo/requirements.txt` 로 설치하세요."
        ) from exc

    stem = os.path.join(out_dir, "source_video")
    opts = {
        "outtmpl": stem + ".%(ext)s",
        # 화질 상한을 두는 이유: 강의 영상은 음성 전사와 슬라이드 글자만 보면 된다.
        # 상한을 안 걸었더니 유튜브 4K 원본으로 690MB 를 받아 왔다(실측).
        # 720p 면 슬라이드 OCR 에 충분하다.
        "format": f"bestvideo[height<=?{MAX_HEIGHT}]+bestaudio/best[height<=?{MAX_HEIGHT}]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,       # 재생목록 링크를 줘도 그 영상 하나만
        "overwrites": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
    }
    print("[다운로드] yt-dlp 로 내려받는 중 ...")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(src, download=True)
    except Exception as exc:  # yt_dlp.DownloadError 등
        raise RuntimeError(f"영상을 내려받지 못했습니다: {exc}") from exc

    # 합치기(merge)를 거치면 확장자가 바뀌므로 실제로 생긴 파일을 찾는다.
    path = ydl.prepare_filename(info)
    if not os.path.exists(path):
        found = sorted(glob.glob(stem + ".*"), key=os.path.getmtime)
        if not found:
            raise RuntimeError("내려받기는 끝났는데 파일이 없습니다.")
        path = found[-1]
    # 어느 쪽으로 찾았든 검사는 똑같이 거친다. 예전에는 prepare_filename 쪽 경로만
    # 검사 없이 바로 돌려줘서, 직접 링크가 오류 HTML 을 저장한 경우가 새어 나갔다.
    return _verify_media(path)


def _verify_media(path: str) -> str:
    """받아온 게 정말 영상인지 그 자리에서 확인한다.

    여기서 안 막으면 전사 단계까지 끌고 가서 엉뚱한 오류로 터진다. 실제로 유튜브
    링크에서 재생 페이지 HTML 이 `source_video.mp4` 로 저장된 적이 있다. 구글드라이브도
    권한이 없으면 같은 식으로 안내 페이지가 내려온다.
    """
    if not os.path.exists(path):
        raise RuntimeError(f"내려받기에 실패했습니다: {path} 가 만들어지지 않았습니다.")
    size = os.path.getsize(path)
    if size < MIN_MEDIA_BYTES:
        raise RuntimeError(
            f"내려받은 파일이 너무 작습니다({size:,}바이트). 영상이 아니라 오류 페이지일 수 있습니다."
        )
    with open(path, "rb") as f:
        head = f.read(512).lstrip()
    if head[:1] == b"<" or head[:9].lower() == b"<!doctype":
        raise RuntimeError(
            "영상 대신 웹페이지가 내려왔습니다. 공개 권한(구글드라이브는 '링크가 있는 모든 사용자')을"
            " 확인하세요."
        )
    return path


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
        # gdown 은 판(version)에 따라 실패를 예외로 던지기도 하고 None 을 돌려주기도 한다.
        # 돌려준 값을 안 보면 실패해도 없는 경로를 그대로 넘기게 된다.
        try:
            got = gdown.download(id=gid, output=dest, quiet=False)
        except Exception as exc:
            raise RuntimeError(f"구글드라이브에서 내려받지 못했습니다: {exc}") from exc
        if not got:
            raise RuntimeError(
                "구글드라이브에서 내려받지 못했습니다. 공유 권한이 '링크가 있는 모든 사용자'인지"
                " 확인하세요."
            )
        return _verify_media(dest)

    if src.startswith("http://") or src.startswith("https://"):
        return _download_link(src, out_dir)

    raise FileNotFoundError(f"입력을 찾을 수 없습니다: {src}")
