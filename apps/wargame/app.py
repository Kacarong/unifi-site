"""현대전 전략 시뮬레이션 — 하츠 오브 아이언 스타일 국가 전략 게임 (프론트엔드 전용).

게임 소스는 이 레포에 복사하지 않는다. 게임 저장소에서 빌드해 배포 폴더
(기본 ~/wargame-site, wargame.kacarong.kr 과 같은 폴더)에 올리면 여기서도
그대로 보인다. 정적 파일은 요청마다 디스크에서 읽으므로 게임을 다시 배포해도
이 사이트를 재시작할 필요가 없다.

    bun run build && rsync -a --delete dist/ ~/wargame-site/   # 게임 저장소에서

다른 곳에 빌드해 뒀다면 WARGAME_DIST 환경변수로 그 폴더를 가리킨다.
"""
import os

from server.registry import AppSpec

SPEC = AppSpec(
    id="wargame",
    name="현대전 전략 시뮬레이션",
    tagline="실제 세계지도 위에서 나라 하나를 맡아 운영하는 전략 게임",
    accent="#c8a24a",
    icon="🎖️",
    description=(
        "2026년 또는 1980년 1월 1일에서 나라 하나를 골라 경제·외교·의회·군대를 운영합니다. "
        "실제 행정구역 지도와 실존 무기 체계를 쓰고, 시간은 멈추고 흘릴 수 있습니다. "
        "저장은 이 브라우저에만 남습니다."
    ),
    tags=["게임", "전략", "프론트엔드"],
    static_dir=os.environ.get("WARGAME_DIST") or os.path.expanduser("~/wargame-site"),
)
