"""앱 레지스트리 — `apps/<id>/app.py` 를 스캔해서 통합 사이트에 붙인다.

새 사이트를 추가하려면 `apps/` 아래에 폴더 하나 만들고 `app.py` 에서
`SPEC = AppSpec(...)` 만 정의하면 된다. 서버 코드는 건드리지 않는다.
폴더 이름은 파이썬 식별자로 써야 한다(영문 소문자/숫자/언더스코어).

`app.py` 는 "가볍게" 유지한다. 무거운 의존성(torch, playwright 등)은
`router_factory` 안에서 import 해야 한다. 그래야 해당 앱의 패키지가
설치되지 않아도 나머지 앱과 포털은 정상 동작한다.
"""
from __future__ import annotations

import importlib
import os
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

APPS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps")


@dataclass
class BuildSpec:
    """프론트엔드 빌드가 필요한 앱용 정보 (scripts/build.py 가 사용)."""

    cwd: str  # 앱 폴더 기준 상대경로
    install: Optional[str] = None
    command: Optional[str] = None


@dataclass
class AppSpec:
    id: str
    name: str
    description: str = ""
    icon: str = "🧩"
    tags: list[str] = field(default_factory=list)

    # /apps/<id> 로 서빙할 정적 프론트엔드 (앱 폴더 기준 상대경로)
    static_dir: Optional[str] = None
    # /api/<id> 로 마운트할 APIRouter 를 돌려주는 함수 (지연 import 용)
    router_factory: Optional[Callable[[], object]] = None
    # 프론트 빌드 정보
    build: Optional[BuildSpec] = None
    # 앱 전용 추가 의존성 파일 (앱 폴더 기준)
    requirements: Optional[str] = None
    # 별도 설치/실행이 필요할 때 포털에 띄울 안내
    notes: str = ""
    enabled: bool = True

    # --- 런타임에 채워지는 값 ---
    dir: str = ""
    error: str = ""

    @property
    def static_path(self) -> Optional[str]:
        if not self.static_dir:
            return None
        return os.path.join(self.dir, self.static_dir)

    @property
    def has_frontend(self) -> bool:
        p = self.static_path
        return bool(p and os.path.isdir(p) and os.path.exists(os.path.join(p, "index.html")))

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.error:
            return "error"
        if self.static_dir and not self.has_frontend:
            return "needs_build"
        return "ready"

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "tags": self.tags,
            "status": self.status,
            "error": self.error,
            "notes": self.notes,
            "url": f"/apps/{self.id}/" if self.has_frontend else None,
            "api": f"/api/{self.id}" if self.router_factory else None,
        }


def _load_spec(app_dir: str) -> Optional[AppSpec]:
    entry = os.path.join(app_dir, "app.py")
    if not os.path.exists(entry):
        return None

    app_id = os.path.basename(app_dir)
    try:
        module = importlib.import_module(f"apps.{app_id}.app")
    except Exception:
        return AppSpec(
            id=app_id,
            name=app_id,
            description="앱 로드 실패",
            dir=app_dir,
            error=traceback.format_exc(limit=3),
        )

    app_spec = getattr(module, "SPEC", None)
    if not isinstance(app_spec, AppSpec):
        return AppSpec(
            id=app_id,
            name=app_id,
            dir=app_dir,
            error="app.py 에 AppSpec 인스턴스인 SPEC 이 없습니다.",
        )

    app_spec.dir = app_dir
    return app_spec


def discover(apps_dir: str = APPS_DIR) -> list[AppSpec]:
    """apps/ 하위 폴더를 훑어 AppSpec 목록을 만든다 (이름순)."""
    found: list[AppSpec] = []
    if not os.path.isdir(apps_dir):
        return found

    for name in sorted(os.listdir(apps_dir)):
        if name.startswith((".", "_")):
            continue
        app_dir = os.path.join(apps_dir, name)
        if not os.path.isdir(app_dir):
            continue
        spec = _load_spec(app_dir)
        if spec is not None:
            found.append(spec)
    return found
