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
import re
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


# 파일 이름에 내용 해시가 박힌 빌드 산출물 (예: index-BnQh4cpB.js).
# 내용이 바뀌면 이름이 바뀌므로 영구 캐시해도 안전하다.
_HASHED_ASSET = re.compile(r"/assets/[^/]+-[A-Za-z0-9_-]{8,}\.(js|css|woff2?|png|svg)$")


@app.middleware("http")
async def _cache_policy(request: Request, call_next):
    """캐시 규칙을 명시한다.

    헤더를 아예 안 주면 브라우저가 스스로 '아직 신선하다'고 판단해 서버에
    묻지도 않고 옛 파일을 쓴다. 그래서 화면을 고쳐도 이미 방문했던 기기에서는
    한참 동안 그대로 보인다. 실제로 그 현상이 있었다.

    - 글꼴, 해시 붙은 빌드 파일: 내용이 안 바뀌므로 영구 캐시
    - 나머지(HTML·CSS·JS·데이터): 매번 확인만 시킨다. 안 바뀌었으면 서버가
      304 로 답하므로 본문은 다시 받지 않아 느려지지 않는다.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/fonts/") or _HASHED_ASSET.search(path):
        response.headers["cache-control"] = "public, max-age=31536000, immutable"
    else:
        response.headers.setdefault("cache-control", "no-cache")
    return response


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


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """브라우저는 <link rel=icon> 이 있어도 /favicon.ico 를 찾는 경우가 있다.
    없으면 콘솔에 404 가 남으므로 PNG 아이콘으로 응답한다."""
    return FileResponse(os.path.join(SHELL_STATIC, "icon-180.png"), media_type="image/png")


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
