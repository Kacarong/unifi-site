"""unifi-site — 여러 개인 프로젝트를 한 사이트로 묶는 통합 셸(FastAPI).

- `/`             포털(앱 런처)
- `/apps/<id>/`   각 앱의 프론트엔드
- `/api/<id>/…`   각 앱의 백엔드 API
- `/api/_apps`    등록된 앱 목록(JSON)

앱은 `apps/` 폴더를 스캔해서 자동 등록된다. server 코드는 앱을 알지 못한다.
"""
from __future__ import annotations

import logging
import os
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth
from .registry import AppSpec, discover

log = logging.getLogger("unifi")
logging.basicConfig(level=os.environ.get("UNIFI_LOG_LEVEL", "INFO"))

HERE = os.path.dirname(os.path.abspath(__file__))
SHELL_STATIC = os.path.join(HERE, "static")

app = FastAPI(title="unifi-site", description="개인 프로젝트 통합 사이트")

APPS: list[AppSpec] = discover()


def _mount_apps() -> None:
    for spec in APPS:
        if not spec.enabled:
            log.info("app %-10s skipped (disabled)", spec.id)
            continue

        if spec.router_factory:
            try:
                router = spec.router_factory()
                app.include_router(router, prefix=f"/api/{spec.id}", tags=[spec.id])
            except Exception:
                spec.error = traceback.format_exc(limit=3)
                log.warning("app %-10s API 등록 실패 (의존성 미설치?)\n%s", spec.id, spec.error)

        if spec.has_frontend:
            app.mount(
                f"/apps/{spec.id}",
                StaticFiles(directory=spec.static_path, html=True),
                name=f"app-{spec.id}",
            )

        log.info("app %-10s %-12s %s", spec.id, spec.status, spec.name)


LOGIN_PAGE = os.path.join(SHELL_STATIC, "login.html")


@app.middleware("http")
async def _password_gate(request: Request, call_next):
    """공개 배포용 비밀번호 게이트 (UNIFI_PASSWORD 가 있을 때만 동작)."""
    path = request.url.path
    if (
        not auth.enabled()
        or auth.is_public_path(path)
        or auth.valid(request.cookies.get(auth.COOKIE_NAME))
    ):
        return await call_next(request)

    if path.startswith("/api/"):
        return JSONResponse({"detail": "로그인이 필요합니다"}, status_code=401)
    return FileResponse(LOGIN_PAGE, status_code=401, media_type="text/html")


class LoginBody(BaseModel):
    password: str = ""


@app.post("/api/_login")
def login(body: LoginBody, request: Request) -> JSONResponse:
    if not auth.enabled():
        return JSONResponse({"ok": True, "note": "비밀번호가 설정되지 않았습니다"})

    client = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    try:
        ok = auth.check_password(body.password, client)
    except auth.TooManyAttempts as exc:
        return JSONResponse({"detail": str(exc), "retry_after": exc.retry_after}, status_code=429)

    if not ok:
        log.warning("로그인 실패 (%s)", client)
        return JSONResponse({"detail": "비밀번호가 맞지 않습니다"}, status_code=401)

    res = JSONResponse({"ok": True})
    res.set_cookie(
        auth.COOKIE_NAME,
        auth.issue(),
        max_age=auth.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
    )
    return res


@app.post("/api/_logout")
def logout() -> JSONResponse:
    res = JSONResponse({"ok": True})
    res.delete_cookie(auth.COOKIE_NAME)
    return res


@app.get("/api/_apps")
def list_apps() -> JSONResponse:
    return JSONResponse([s.to_json() for s in APPS])


@app.get("/api/_health")
def health() -> dict:
    return {
        "ok": True,
        "apps": {s.id: s.status for s in APPS},
    }


_mount_apps()

# 포털 셸은 마지막에 마운트해야 다른 라우트를 가리지 않는다.
if os.path.isdir(SHELL_STATIC):
    app.mount("/", StaticFiles(directory=SHELL_STATIC, html=True), name="shell")
else:  # pragma: no cover - 개발 중 셸이 없을 때의 안전망
    @app.get("/", response_class=HTMLResponse)
    def _fallback() -> str:
        return "<h1>unifi-site</h1><p>포털 정적 파일이 없습니다.</p>"
