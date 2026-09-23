"""입력 소스 해석(apps/exvideo/exvideo/download.py) 테스트.

    python3 tests/test_exvideo_download.py

여기서 고정하는 것 — 실제로 났던 사고들이다.
  1. 유튜브 주소를 넣으면 영상이 내려와야 한다. 예전에는 링크를 그대로
     urlretrieve 해서 **재생 페이지 HTML** 이 `source_video.mp4` 로 저장됐고,
     한참 뒤 전사 단계에서 알 수 없는 오류로 터졌다.
  2. 확장자 없는 링크도 이름이 제대로 붙어야 한다. 예전 코드의
     `"source_video" + ext or ".mp4"` 는 연산자 우선순위 때문에 `.mp4`
     기본값이 한 번도 적용되지 않았다.
  3. 화질 상한이 걸려 있어야 한다. 상한이 없어 4K 원본 690MB 를 받은 적이 있다.

망 접속은 하지 않는다. yt-dlp 는 가짜로 바꿔치기한다.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from apps.exvideo.exvideo import download  # noqa: E402

MIN_BYTES = download.MIN_MEDIA_BYTES

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}: got {got!r}, want {want!r}")
        FAILURES.append(label)


def ok(label: str, cond, detail: str = "") -> None:
    check(label + (f" ({detail})" if detail else ""), bool(cond), True)


class FakeYDL:
    """호출 옵션을 기록하고, 진짜로 파일 하나를 만들어 주는 가짜 yt-dlp."""

    last_opts: dict = {}
    made_ext = "mp4"

    def __init__(self, opts):
        FakeYDL.last_opts = opts
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=True):
        # 인자 이름 download 가 모듈 이름을 가리므로 미리 빼 둔 상수를 쓴다.
        self.path = self.opts["outtmpl"].replace("%(ext)s", FakeYDL.made_ext)
        with open(self.path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42")   # mp4 헤더 흉내
            f.write(b"\x00" * MIN_BYTES)           # 크기 검사를 통과할 만큼
        return {"url": url}

    def prepare_filename(self, info):
        return self.path


class FakeYTDLPModule:
    YoutubeDL = FakeYDL


def test_youtube_goes_through_ytdlp() -> None:
    print("\n[1] 유튜브 주소 — HTML 이 아니라 영상이 내려온다")
    work = tempfile.mkdtemp(prefix="unifi-dl-")
    try:
        sys.modules["yt_dlp"] = FakeYTDLPModule
        path = download.resolve_input("https://www.youtube.com/watch?v=abc123", work)
        ok("파일이 생겼다", os.path.exists(path), path)
        check("이름이 source_video.mp4", os.path.basename(path), "source_video.mp4")
        with open(path, "rb") as f:
            head = f.read(16)
        ok("HTML 이 아니다", not head.lstrip().lower().startswith(b"<"), repr(head))
    finally:
        sys.modules.pop("yt_dlp", None)
        shutil.rmtree(work, ignore_errors=True)


def test_quality_cap() -> None:
    print("\n[2] 화질 상한 — 4K 원본을 통째로 받지 않는다")
    work = tempfile.mkdtemp(prefix="unifi-dl-")
    try:
        sys.modules["yt_dlp"] = FakeYTDLPModule
        download.resolve_input("https://www.youtube.com/watch?v=abc123", work)
        fmt = FakeYDL.last_opts.get("format", "")
        ok("format 에 높이 상한이 있다", f"height<=?{download.MAX_HEIGHT}" in fmt, fmt)
        check("기본 상한은 720", download.MAX_HEIGHT, 720)
        check("재생목록은 한 개만", FakeYDL.last_opts.get("noplaylist"), True)
    finally:
        sys.modules.pop("yt_dlp", None)
        shutil.rmtree(work, ignore_errors=True)


def test_merged_extension() -> None:
    print("\n[3] 합치기로 확장자가 바뀌어도 파일을 찾는다")
    work = tempfile.mkdtemp(prefix="unifi-dl-")
    try:
        sys.modules["yt_dlp"] = FakeYTDLPModule

        class MovedYDL(FakeYDL):
            def prepare_filename(self, info):
                return os.path.join(work, "source_video.webm")  # 실제로는 안 남은 이름

        FakeYTDLPModule.YoutubeDL = MovedYDL
        path = download.resolve_input("https://example.com/lecture", work)
        ok("실제로 생긴 파일을 찾아낸다", os.path.exists(path), path)
        check("확장자는 진짜 만들어진 쪽", os.path.basename(path), "source_video.mp4")
    finally:
        FakeYTDLPModule.YoutubeDL = FakeYDL
        sys.modules.pop("yt_dlp", None)
        shutil.rmtree(work, ignore_errors=True)


def test_local_and_gdrive() -> None:
    print("\n[4] 로컬 경로와 구글드라이브 링크")
    work = tempfile.mkdtemp(prefix="unifi-dl-")
    try:
        local = os.path.join(work, "already.mp4")
        with open(local, "wb") as f:
            f.write(b"x")
        check("로컬 파일은 그대로 돌려준다", download.resolve_input(local, work), local)

        gid = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
        check("/d/ 형식 id 추출",
              download._gdrive_id(f"https://drive.google.com/file/d/{gid}/view"), gid)
        check("?id= 형식 id 추출",
              download._gdrive_id(f"https://drive.google.com/uc?id={gid}"), gid)
        check("id 가 없으면 None", download._gdrive_id("https://drive.google.com/"), None)

        try:
            download.resolve_input("https://drive.google.com/file/d/short/view", work)
            ok("id 없는 드라이브 링크는 거절한다", False)
        except ValueError as exc:
            ok("id 없는 드라이브 링크는 거절한다", "파일 ID" in str(exc), str(exc))

        try:
            download.resolve_input("그냥아무말", work)
            ok("링크도 파일도 아니면 거절한다", False)
        except FileNotFoundError:
            ok("링크도 파일도 아니면 거절한다", True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


class FakeGdown:
    """실패 방식을 골라 흉내 낼 수 있는 가짜 gdown."""

    mode = "ok"   # ok | none | raise | html | tiny

    @staticmethod
    def download(id=None, output=None, quiet=False):
        if FakeGdown.mode == "none":
            return None                      # 옛 판은 실패를 None 으로 알린다
        if FakeGdown.mode == "raise":
            raise RuntimeError("Permission denied")
        with open(output, "wb") as f:
            if FakeGdown.mode == "html":
                f.write(b"<!DOCTYPE html><html><body>\xeb\xa1\x9c\xea\xb7\xb8\xec\x9d\xb8"
                        + b" " * MIN_BYTES)
            elif FakeGdown.mode == "tiny":
                f.write(b"\x00\x00\x00\x18ftypmp42")
            else:
                f.write(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * MIN_BYTES)
        return output


def test_gdrive_failures() -> None:
    """구글드라이브가 실패했는데 성공한 척하지 않는가.

    예전에는 gdown 의 반환값을 안 보고 무조건 경로를 돌려줬다. 실패해도 없는 파일을
    넘기고, 권한이 없으면 안내 페이지를 영상인 척 넘겼다.
    """
    print("\n[5] 구글드라이브 실패 — 성공한 척하지 않는다")
    work = tempfile.mkdtemp(prefix="unifi-dl-")
    saved = sys.modules.get("gdown")
    url = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"
    try:
        sys.modules["gdown"] = FakeGdown

        FakeGdown.mode = "ok"
        path = download.resolve_input(url, work)
        ok("정상일 때는 경로를 준다", os.path.exists(path), path)

        for mode, hint in (("none", "공유 권한"), ("raise", "내려받지 못했습니다"),
                           ("html", "웹페이지"), ("tiny", "너무 작습니다")):
            FakeGdown.mode = mode
            try:
                download.resolve_input(url, work)
                ok(f"{mode}: 실패를 잡아낸다", False)
            except RuntimeError as exc:
                ok(f"{mode}: 실패를 잡아낸다", hint in str(exc), str(exc)[:60])
    finally:
        FakeGdown.mode = "ok"
        sys.modules.pop("gdown", None)
        if saved is not None:
            sys.modules["gdown"] = saved
        shutil.rmtree(work, ignore_errors=True)


def test_missing_ytdlp_message() -> None:
    print("\n[6] yt-dlp 가 없을 때 — 무슨 일인지 알 수 있게 말해 준다")
    work = tempfile.mkdtemp(prefix="unifi-dl-")
    saved = sys.modules.pop("yt_dlp", None)
    try:
        sys.modules["yt_dlp"] = None  # import 시 ImportError 를 내게 한다
        try:
            download.resolve_input("https://www.youtube.com/watch?v=abc123", work)
            ok("설치 안내를 준다", False)
        except RuntimeError as exc:
            ok("설치 안내를 준다", "yt-dlp" in str(exc) and "requirements" in str(exc), str(exc))
    finally:
        sys.modules.pop("yt_dlp", None)
        if saved is not None:
            sys.modules["yt_dlp"] = saved
        shutil.rmtree(work, ignore_errors=True)


def test_link_download_is_always_verified() -> None:
    """내려받은 파일이 영상인지 검사하는 걸 어느 경로로도 건너뛰지 않는가.

    prepare_filename 이 돌려준 경로가 존재하면 검사 없이 바로 돌려주던 때가 있었다.
    직접 링크(.mp4)가 오류 HTML 을 그 이름으로 저장한 경우 그대로 새어 나갔다.
    """
    print("\n[7] 링크 내려받기 — 어느 경로로 찾았든 영상인지 검사한다")
    work = tempfile.mkdtemp(prefix="unifi-dl-")
    try:
        sys.modules["yt_dlp"] = FakeYTDLPModule

        class HtmlYDL(FakeYDL):
            """prepare_filename 경로에 **HTML** 을 남기는 가짜."""

            def extract_info(self, url, download=True):
                self.path = self.opts["outtmpl"].replace("%(ext)s", "mp4")
                with open(self.path, "wb") as f:
                    f.write(b"<!DOCTYPE html><html><body>Not Found" + b" " * MIN_BYTES)
                return {"url": url}

        FakeYTDLPModule.YoutubeDL = HtmlYDL
        try:
            download.resolve_input("https://example.com/lecture.mp4", work)
            ok("HTML 이 내려오면 거절한다", False)
        except RuntimeError as exc:
            ok("HTML 이 내려오면 거절한다", "웹페이지" in str(exc), str(exc)[:60])

        class TinyYDL(FakeYDL):
            """prepare_filename 경로에 너무 작은 파일을 남기는 가짜."""

            def extract_info(self, url, download=True):
                self.path = self.opts["outtmpl"].replace("%(ext)s", "mp4")
                with open(self.path, "wb") as f:
                    f.write(b"\x00\x00\x00\x18ftypmp42")
                return {"url": url}

        FakeYTDLPModule.YoutubeDL = TinyYDL
        try:
            download.resolve_input("https://example.com/lecture.mp4", work)
            ok("토막 파일이면 거절한다", False)
        except RuntimeError as exc:
            ok("토막 파일이면 거절한다", "너무 작습니다" in str(exc), str(exc)[:60])
    finally:
        FakeYTDLPModule.YoutubeDL = FakeYDL
        sys.modules.pop("yt_dlp", None)
        shutil.rmtree(work, ignore_errors=True)


def run() -> None:
    test_youtube_goes_through_ytdlp()
    test_quality_cap()
    test_merged_extension()
    test_local_and_gdrive()
    test_gdrive_failures()
    test_missing_ytdlp_message()
    test_link_download_is_always_verified()


if __name__ == "__main__":
    run()
    print()
    if FAILURES:
        print(f"실패 {len(FAILURES)}건: " + ", ".join(FAILURES))
        sys.exit(1)
    print("모두 통과")
