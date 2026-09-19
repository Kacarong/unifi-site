"""ex-video — 강의 영상에서 전사·슬라이드 텍스트·그림을 뽑아내는 앱.

무거운 의존성(opencv / faster-whisper / easyocr)은 실제 처리 시점에만
import 되므로, 설치되지 않은 환경에서도 포털과 다른 앱은 그대로 뜬다.
원본 레포: https://github.com/Kacarong/ex-video
"""
from server.registry import AppSpec


def _router_factory():
    from .api import router

    return router


SPEC = AppSpec(
    id="exvideo",
    name="ex-video",
    icon="🎬",
    description="강의 영상(드라이브 링크·URL·로컬 경로)을 넣으면 음성 전사 + 슬라이드 OCR + 그림 크롭을 묶어 bundle.md 로 만들어 줍니다.",
    tags=["영상", "OCR", "GPU"],
    static_dir="web/static",
    router_factory=_router_factory,
    requirements="requirements.txt",
)
