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


# 휴대폰·태블릿 판별. 포털 표시와 직접 접속 차단이 어긋나지 않도록
# 판단은 서버 한 곳에서만 한다.
_MOBILE_UA = re.compile(
    r"Android|iPhone|iPod|iPad|Windows Phone|IEMobile|Opera Mini|Mobile Safari",
    re.IGNORECASE,
)


def is_mobile(request: Request) -> bool:
    return bool(_MOBILE_UA.search(request.headers.get("user-agent", "")))


DESKTOP_ONLY_PAGE = """<!doctype html><html lang="ko"><head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="theme-color" content="#070b16" /><meta name="color-scheme" content="dark" />
<title>{name} · PC 전용</title>
<link rel="stylesheet" href="/ui.css" />
<style>
  .only {{ min-height: 100dvh; display: grid; place-items: center; padding: 24px; }}
  .only .panel {{ max-width: 380px; text-align: center; display: grid; gap: 14px; }}
  .only .big {{ font-size: 40px; }}
</style></head><body>
<header class="topbar"><a class="back" href="/">← unifi</a></header>
<div class="only"><div class="panel">
  <div class="big">{icon}</div>
  <h1>{name}</h1>
  <p class="muted">이 앱은 PC에서만 쓸 수 있습니다.<br />{reason}</p>
  <a class="btn primary" href="/">다른 앱 보기</a>
</div></div></body></html>"""


@app.middleware("http")
async def _desktop_only_gate(request: Request, call_next):
    """PC 전용 앱을 휴대폰으로 직접 열면 안내 화면을 보여 준다."""
    path = request.url.path
    if path.startswith("/apps/") and is_mobile(request):
        app_id = path.split("/")[2] if len(path.split("/")) > 2 else ""
        spec = next((s for s in APPS if s.id == app_id), None)
        if spec and spec.desktop_only:
            return HTMLResponse(
                DESKTOP_ONLY_PAGE.format(
                    name=spec.name,
                    icon=spec.icon,
                    reason=spec.notes or "로컬 PC 프로그램이 함께 있어야 동작합니다.",
                ),
                status_code=200,
            )
    return await call_next(request)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """브라우저는 <link rel=icon> 이 있어도 /favicon.ico 를 찾는 경우가 있다.
    없으면 콘솔에 404 가 남으므로 PNG 아이콘으로 응답한다."""
    return FileResponse(os.path.join(SHELL_STATIC, "icon-180.png"), media_type="image/png")


@app.get("/api/_apps")
def list_apps(request: Request) -> JSONResponse:
    mobile = is_mobile(request)
    out = []
    for spec in APPS:
        item = spec.to_json()
        if mobile and spec.desktop_only:
            # 휴대폰에서는 눌러도 못 쓰는 앱이니 처음부터 그렇게 보여 준다
            item["status"] = "desktop_only"
            item["url"] = None
        out.append(item)
    return JSONResponse(out)


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
