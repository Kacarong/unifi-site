"""가상 주식 모의투자 — virtual-stock.kro.kr 로 보내 주는 바로가기 앱.

사이트 자체는 여기서 돌리지 않는다. 원래 서버(virtual-stock-site-bot 컨테이너,
http://virtual-stock.kro.kr/)를 그대로 쓰고, 포털 카드나 /apps/vstock/ 주소로
들어오면 그쪽으로 넘겨 준다. 그래서 가상 주식 사이트를 고치거나 다시 배포해도
이 레포는 손댈 필요가 없다.

하위 경로와 쿼리는 그대로 붙여 넘긴다(/apps/vstock/ranking → …/ranking).
주소를 바꾸려면 VSTOCK_URL 환경변수를 준다. 302 를 쓰는 건 주소를 바꿨을 때
브라우저가 옛 주소를 기억하지 않게 하려는 것이다.
"""
import os

from server.registry import AppSpec

TARGET = (os.environ.get("VSTOCK_URL") or "http://virtual-stock.kro.kr").rstrip("/")


def _mount(app):
    from fastapi import Request
    from fastapi.responses import RedirectResponse

    @app.get("/apps/vstock", include_in_schema=False)
    @app.get("/apps/vstock/{rest:path}", include_in_schema=False)
    def _go(request: Request, rest: str = ""):
        url = f"{TARGET}/{rest}"
        if request.url.query:
            url += f"?{request.url.query}"
        return RedirectResponse(url, status_code=302)


SPEC = AppSpec(
    id="vstock",
    name="가상 주식",
    short_name="주식",
    tagline="실제 시세로 해 보는 주식·코인 모의투자",
    accent="#a78bfa",
    icon="📈",
    description=(
        "가상 돈으로 국내·해외 주식과 코인을 사고팔아 보는 모의투자 사이트입니다. "
        "누르면 virtual-stock.kro.kr 로 이동하며, 사이트는 그쪽 서버에서 그대로 돌아갑니다."
    ),
    tags=["주식", "모의투자", "바로가기"],
    mount=_mount,
)
