"""임대·분양 공고 알림 — LH·SH·GH·청약홈 공고를 모아 조건에 맞는 새 공고를 디스코드로 알린다.

원본 레포: https://github.com/Kacarong/housing-alert (서버 렌더링 화면이라 /apps/housing 아래에 직접 붙인다)
"""
from server.registry import AppSpec


def _mount(app) -> None:
    from .housing_alert import bootstrap, db
    from .housing_alert.config import load_config
    from .housing_alert.web.app import build_router, mount_static
    from .worker import Worker

    cfg = load_config()
    conn = db.connect(cfg.db_path)
    try:
        bootstrap.init_db(conn, cfg)  # 처음 뜰 때만 예시 필터(꺼진 상태)를 넣는다
    finally:
        conn.close()
    app.include_router(build_router(cfg))
    mount_static(app, cfg)

    from fastapi.responses import RedirectResponse

    @app.get(cfg.base_path, include_in_schema=False)
    def _slash():  # 끝에 / 없이 들어와도 대시보드로
        return RedirectResponse(cfg.base_path + "/")

    # 알리미라서 사이트가 떠 있는 동안 늘 돌아야 한다
    Worker(cfg).start()


SPEC = AppSpec(
    id="housing",
    name="임대·분양 공고 알림",
    tagline="LH·SH·GH·청약홈 공고 모음 + 조건 맞는 새 공고 알림",
    accent="#38bdf8",
    icon="🏠",
    description=(
        "LH·SH·GH와 청약홈·LH 공공데이터 API에서 임대·분양 공고를 모아, 저장한 조건(필터)에 맞는 새 공고를 "
        "디스코드로 알립니다. 협동조합형 민간임대(조합원 모집) 의심 공고는 걸러 냅니다."
    ),
    tags=["부동산", "알림"],
    mount=_mount,
    requirements="requirements.txt",
)
