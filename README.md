# unifi-site

개인 프로젝트들을 **한 사이트**로 묶는 통합 셸. 각 프로젝트는 `apps/` 아래
독립 폴더로 들어가고, 포털이 이를 자동으로 찾아 붙인다. 새 사이트를 추가할 때
서버 코드를 고칠 필요가 없다.

```
/                 포털 (앱 런처)
/apps/<id>/       각 앱 프론트엔드
/api/<id>/…       각 앱 백엔드
/api/_apps        등록된 앱 목록(JSON)
```

## 지금 들어있는 앱

| 앱 | 설명 | 구성 |
| --- | --- | --- |
| 🌍 `geoglobe` | Cesium 지구본 지리 학습 + 퀴즈 | 프론트엔드 전용 (Vite 빌드 필요) |
| 🎬 `exvideo` | 강의 영상 → 전사 + 슬라이드 OCR + 그림 추출 | FastAPI + GPU 파이프라인 |
| 🎟️ `cgvmacro` | CGV 취소표·상영오픈 감시와 디스코드 알림 | 서버 감시 + 로컬 PC 선점 에이전트 |

원본 레포: [geoglobe](https://github.com/Kacarong/geoglobe) ·
[ex-video](https://github.com/Kacarong/ex-video) ·
[cgv-macro](https://github.com/Kacarong/cgv-macro)

## 실행

```bash
git clone https://github.com/Kacarong/unifi-site.git
cd unifi-site
./run.sh            # 윈도우는 run.bat
```

`run.sh` 가 `.venv` 를 만들고 최소 의존성만 설치한 뒤 http://localhost:8000 을 띄운다.
앱별 추가 의존성은 필요한 앱만 골라 설치하면 된다.

```bash
.venv/bin/pip install -r apps/exvideo/requirements.txt    # 영상 처리(무거움, GPU 권장)
python scripts/build.py geoglobe                          # 지구본 프론트 빌드 (npm 필요)
```

**의존성을 설치하지 않아도 서버는 뜬다.** 해당 앱만 포털에서 `오류`/`빌드 필요` 로
표시되고 나머지는 정상 동작한다.

## 구조

```
server/           통합 셸
  main.py         FastAPI 앱 — 앱 자동 마운트
  registry.py     apps/ 스캔 + AppSpec 정의
  paths.py        앱별 데이터 경로
  static/         포털 화면
apps/<id>/        앱 하나 = 폴더 하나
  app.py          SPEC (메타데이터 + 라우터 팩토리)
  api.py          백엔드 (있는 경우)
  web/            프론트엔드
scripts/build.py  프론트 빌드가 필요한 앱 빌드
docs/             문서
data/             런타임 데이터 (git 제외)
```

## 새 앱 추가

[docs/ADDING_AN_APP.md](docs/ADDING_AN_APP.md) 참고. 요약하면 폴더 만들고:

```python
# apps/mysite/app.py
from server.registry import AppSpec

SPEC = AppSpec(id="mysite", name="내 사이트", icon="✨", static_dir="web")
```

## 각 앱을 따로 고치기

앱끼리 서로 import 하지 않는다. `apps/geoglobe/` 만 고치면 다른 앱에 영향이 없고,
프론트 빌드도 앱 단위로 따로 돈다. 원본 레포의 변경분을 가져올 때도
해당 앱 폴더에만 반영하면 된다.

## cgv-macro 는 왜 반쪽인가

좌석 선점은 **로그인된 크롬**이 필요해서 서버에서 할 수 없다. 그래서 역할을 나눴다.

- 통합 사이트: 감시 대상 설정 UI, CGV 공개 API 폴링, 취소표/오픈 감지, 디스코드 알림
- 로컬 PC 에이전트: 서버에서 선점 작업을 받아 크롬으로 좌석을 잡고 결제창까지 진입

에이전트 실행법은 [apps/cgvmacro/agent/README.md](apps/cgvmacro/agent/README.md) 참고.
