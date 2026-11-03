"""장학금 알리미 — 대학생 장학금 모음 + 관심 장학금 마감·새 회차 알림.

원본: 공공데이터포털 '한국장학재단_학자금지원정보(대학생)' (매달 갱신, 키 불필요).
"""
from server.registry import AppSpec


def _router_factory():
    from .api import router
    from .worker import worker

    # 알리미라서 사이트가 떠 있는 동안 늘 돌아야 한다. 누가 켜 줄 필요가 없다.
    worker.start()
    return router


SPEC = AppSpec(
    id="scholarship",
    name="장학금 알리미",
    tagline="내 조건에 맞는 대학생 장학금 모음 + 마감 알림",
    accent="#22c55e",
    icon="🎓",
    description=(
        "한국장학재단이 모으는 정부·지자체·재단 장학금을 내 지역·학년·학교·계열로 걸러 봅니다. "
        "관심 표시한 장학금은 마감이 다가오거나 다음 모집이 올라오면 디스코드로 알려 줍니다."
    ),
    tags=["장학금", "알림"],
    static_dir="web",
    router_factory=_router_factory,
)
