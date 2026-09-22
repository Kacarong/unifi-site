"""cgv-macro — CGV 취소표/상영오픈 감시 + 좌석 선점.

웹에서는 감시 대상 설정과 폴링·알림만 한다(로그인·브라우저 불필요).
실제 좌석 선점은 로그인된 크롬이 있는 로컬 PC 에이전트가 맡는다.
원본 레포: https://github.com/Kacarong/cgv-macro
"""
from server.registry import AppSpec


def _router_factory():
    from .api import router

    return router


SPEC = AppSpec(
    id="cgvmacro",
    name="CGV 좌석 감시",
    tagline="취소표·상영 오픈 감시 + 디스코드 알림",
    accent="#ff4a54",
    # 좌석 선점은 로컬 PC 의 크롬을 조작해야 해서 휴대폰에서는 의미가 없다.
    desktop_only=True,
    icon="🎟️",
    description="취소표·상영 오픈을 서버에서 감시하고 디스코드로 알립니다. 좌석 선점은 로컬 PC 에이전트가 로그인된 크롬으로 처리합니다.",
    tags=["감시", "알림", "로컬 에이전트"],
    static_dir="web/static",
    router_factory=_router_factory,
    notes="좌석 선점 기능을 쓰려면 로컬 PC에서 에이전트를 실행해야 합니다 (apps/cgvmacro/agent/README.md).",
)
