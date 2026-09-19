# 새 앱 추가하기

서버 코드는 건드리지 않습니다. `apps/` 아래에 폴더 하나 만들고 `app.py` 에서
`SPEC` 만 정의하면 포털에 자동으로 나타납니다.

## 1. 가장 단순한 경우 — 정적 사이트

```
apps/mysite/
├── __init__.py
├── app.py
└── web/
    └── index.html
```

```python
# apps/mysite/app.py
from server.registry import AppSpec

SPEC = AppSpec(
    id="mysite",
    name="내 사이트",
    icon="✨",
    description="한 줄 설명",
    static_dir="web",
)
```

서버를 다시 띄우면 포털에 카드가 생기고 `/apps/mysite/` 로 열립니다.

## 2. 백엔드가 있는 경우

```python
# apps/mysite/app.py
from server.registry import AppSpec


def _router_factory():
    from .api import router      # 무거운 import 는 전부 여기 안쪽에서
    return router


SPEC = AppSpec(
    id="mysite",
    name="내 사이트",
    static_dir="web",
    router_factory=_router_factory,
    requirements="requirements.txt",
)
```

```python
# apps/mysite/api.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/hello")
def hello():
    return {"ok": True}
```

라우터는 `/api/mysite` 에 붙습니다. 위 예시는 `GET /api/mysite/hello`.

프론트엔드에서는 `const API = '/api/mysite';` 처럼 앱 접두사를 붙여 호출하세요.

## 3. 빌드가 필요한 프론트엔드 (Vite, React 등)

```python
from server.registry import AppSpec, BuildSpec

SPEC = AppSpec(
    id="mysite",
    name="내 사이트",
    static_dir="web/dist",
    build=BuildSpec(cwd="web", install="npm install", command="npm run build"),
)
```

```
python scripts/build.py mysite
```

빌드 전에는 포털에 **빌드 필요** 로 표시됩니다.

## 규칙 몇 가지

- **폴더 이름 = 앱 id** 이고, 파이썬 식별자여야 합니다(영문 소문자·숫자·언더스코어).
- `app.py` 는 가볍게 유지하세요. torch, playwright 같은 무거운 의존성을 `app.py`
  최상단에서 import 하면 그 패키지가 없는 환경에서 포털 전체가 느려지거나
  앱이 `오류` 로 뜹니다. `router_factory` 안에서 import 하면 그 앱만 비활성화됩니다.
- 데이터를 저장해야 하면 `server.paths.data_dir("<앱id>")` 를 쓰세요.
  `data/` 는 git 에서 제외돼 있습니다.
- 앱 전용 의존성은 `apps/<id>/requirements.txt` 에 따로 두고,
  `SPEC.requirements` 에 파일명을 적어 둡니다.

## 앱 끄기

`SPEC` 에 `enabled=False` 를 주면 포털에 `꺼짐` 으로만 표시되고 마운트되지 않습니다.
폴더를 지울 필요가 없습니다.
