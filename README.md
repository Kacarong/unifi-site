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
| 🎬 `exvideo` | 강의 영상 → 전사·슬라이드 OCR·그림 추출, 그리고 전사 + 강의자료 PDF → 요약정리본 PDF | FastAPI + GPU 파이프라인 |
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

## 요약정리본 (ex-video 의 `/notes`)

전사와 강의자료 PDF 를 넣으면 원하는 구성의 정리본 PDF 가 나온다.
같은 강의에 정리본을 여러 번 만들어도 **원본을 다시 읽지 않는다.**

```
업로드 ──► PyMuPDF 로 글자 추출 (LLM 없음, 토큰 0)
       ──► 구조 보존 인덱스 1회 생성  ← 비용이 드는 유일한 지점
       ──► 인덱스만 입력으로 정리본 PDF (몇 번을 만들든)
```

인덱스는 산문 요약이 아니라 색인이다. 장·절 제목, 개념어, 수식, 예제는 **원문
그대로** 두고 각 항목에 PDF 쪽수와 전사 타임코드를 붙인다. 줄이는 건 설명
문장뿐이라, 나중에 "예상문제 위주로" 같은 요청이 와도 없는 내용을 지어내지 않는다.
"3장 예제만" 처럼 콕 집으면 그 섹션의 원문 구간만 따로 꺼내 쓴다.

### 원하는 대로 정하는 곳

**내용과 구성**은 두 군데서 정한다.

- *어떤 구성으로 만들까요* — 미리 만들어 둔 여섯 조각(목차·핵심요약·개념정리·
  수식정리·예제정리·예상문제)에서 고른다.
- *구성을 직접 적기* — 여섯 조각으로 안 되면 원하는 항목을 한 줄에 하나씩 적는다.
  적으면 위 선택은 무시하고 적은 대로 만든다.
- *프롬프트* — 말투, 분량, 강조할 것처럼 구성으로 표현되지 않는 요구를 적는다.

**PDF 모양**은 *PDF 모양* 칸에서 정한다. 글자 크기, 줄 간격, 여백, 제목 색.
값은 조판이 깨지지 않는 범위로 잘라서 받는다(글자 0.75~1.4배, 줄 간격 1.1~2.2배,
여백 8~40mm). 색이 아닌 값이나 숫자가 아닌 값이 오면 기본값으로 되돌린다.
쓴 설정은 결과물 기록에 `design` 으로 같이 남는다.

### 어떤 모델로 쓸까 — API 키 없이도 된다

정리본을 만들 때 모델을 골라 쓴다. 화면의 드롭다운에는 지금 쓸 수 있는 것만
켜져 있고, 못 쓰는 것은 이유가 함께 적힌다(`GET /api/exvideo/notes/providers`).

| 고르는 값 | 무엇 | 필요한 것 |
| --- | --- | --- |
| `ollama` | 로컬 qwen2.5:7b | 없음. 색인 단계의 기본값 |
| `claude-cli` | **계정 연동 클로드** | 이미 로그인해 둔 Claude Code. **API 키 불필요** |
| `claude` | 클로드 API | `ANTHROPIC_API_KEY` |
| `gemini` | 제미나이 API | `GEMINI_API_KEY` |

`claude-cli` 는 로그인해 둔 Claude Code 를 그대로 불러 쓴다. 키를 따로 발급받을
필요가 없다. 다만 기본 상태로 부르면 도구 정의와 기본 시스템 프롬프트가 딸려와
호출마다 **38,314 토큰**이 먼저 붙으므로, 도구·설정·슬래시명령을 전부 끄고
부른다. 같은 호출이 **151 토큰**으로 떨어진다(둘 다 실측).

```bash
ollama pull qwen2.5:7b                      # 로컬 모델
export EXVIDEO_LLM=claude-cli               # 기본 프로바이더를 바꿀 때
export EXVIDEO_CLAUDE_CLI=/path/to/claude   # PATH 에 없을 때만
export EXVIDEO_CLAUDE_CLI_MODEL=sonnet      # 또는 opus / haiku
export EXVIDEO_LLM_FALLBACK=claude-cli      # 로컬 모델이 한국어를 벗어날 때 넘길 곳
```

**알려진 한계 1 — 로컬 모델의 한국어 이탈.** qwen2.5:7b 는 인덱스에 단단히
묶인 구성(목차·핵심요약·개념정리·수식정리·예제정리)은 한국어를 잘 지키지만,
생성 비중이 큰 **예상문제**에서는 중국어로 샌다(실측 한자 비율 96%). 서버가
이를 감지해 `foreign_ratio` 로 표시하고, `EXVIDEO_LLM_FALLBACK` 이 있으면
그쪽으로 다시 만든다. 같은 강의·같은 구성을 `claude-cli` 로 돌리면 0% 다.

**알려진 한계 2 — 답변이 길면 이어 쓴다.** Claude Code 는 한 번에 다 못 쓰면
알아서 이어 쓰는데, 이은 자리에서 몇 줄이 빠질 수 있다(실측: 200줄 중 2줄).
결과에 `chunks` 로 남기고 1 보다 크면 화면에 경고를 띄운다. 구성을 나눠서
만들면 한 통에 들어간다.

측정값(강의자료 10쪽 + 66분 전사, 원본 13,078자 기준):

| 단계 | 모델 | 입력 토큰 | 비고 |
| --- | --- | --- | --- |
| 인덱스 생성 | ollama | 12,080 | 업로드당 한 번 |
| 정리본 재요청 (목차·요약·개념) | ollama | 4,130 | 인덱스만 입력 — **66% 절감** |
| 예상문제만 | claude-cli | 5,769 | 한국어 이탈 0% (로컬은 96%) |
| 6개 구성 전체 | claude-cli | 6,093 | 10쪽 PDF, 한 통에 완결 |
| 3장 예제만 (원문 재조회 포함) | ollama | 2,363 | 해당 섹션만 — **80% 절감** |

```bash
python3 tests/test_exvideo_notes.py    # LLM 없이 도는 테스트 (가짜 프로바이더)
```

## 영상 넣는 법 (ex-video 의 추출기)

넣을 수 있는 것은 네 가지다. 유튜브 주소, 구글드라이브 공유 링크, 직접 링크
(`.mp4`·`.m3u8`), 서버 로컬 경로. 유튜브와 직접 링크·HLS 는 yt-dlp 가, 구글드라이브는
gdown 이 맡는다.

**720p 까지만 받는다.** 전사와 슬라이드 글자에는 그걸로 충분하다. 상한을 걸기 전에는
유튜브 4K 원본으로 690MB 를 받아 온 적이 있고, 상한을 건 뒤 같은 영상이 78MB 다.
더 높은 화질이 필요하면 `EXVIDEO_MAX_HEIGHT` 로 올린다.

```bash
python3 tests/test_exvideo_download.py   # 망 접속 없이 도는 테스트 (가짜 yt-dlp)
```

### 음성 전사 — GPU 를 쓴다

`faster-whisper` 로 돌고 기본값은 `large-v3` 다. 장치는 알아서 고른다.

장치 판별을 **ctranslate2 에게 직접 묻는다.** 예전에는 torch 로 확인했는데
faster-whisper 는 torch 를 쓰지 않아서, torch 가 없는 환경에서는 GPU 가 멀쩡히
있어도 조용히 CPU 로 떨어졌다. 실제로 그렇게 돌고 있었다.

**GPU 기본 정밀도는 `int8_float16` 이다.** 이 8GB GPU 는 다른 서비스와 나눠 쓰기
때문에(늘 3GB 가까이 물려 있다) `large-v3` 를 `float16` 으로 올리면 VRAM 이 모자란다.
모자라면 `int8_float16` → CPU 순으로 한 단계씩 낮춘다. 낮추기 전에 실패한 모델을
반드시 놓아 준다 — 붙들고 있으면 다음 시도도 똑같이 모자라서, GPU 로 충분히 되는
조합까지 건너뛰고 CPU 로 떨어진다(실측 57초짜리가 355초가 됐다).

pip 로 깔린 CUDA 12 판 cuBLAS·cuDNN 은 동적 링커가 모르는 자리에 있어서, 쓰기 전에
직접 열어 프로세스에 올린다. `LD_LIBRARY_PATH` 를 미리 걸어 둘 필요가 없다.

실측 (10분 15초 한국어 강의, RTX 5050 8GB, 다른 서비스와 공유 중):

| 모델 | 장치 | 걸린 시간 | 비고 |
| --- | --- | --- | --- |
| large-v3 | GPU `int8_float16` | **57초** | 기본값. '미분'을 정확히 받아적는다 |
| large-v3 | CPU `int8` | 355초 | GPU 가 막혔을 때의 마지막 수단 |
| medium | GPU `float16` | 29초 | '미분'을 '미군'으로 적었다 |
| small | GPU `float16` | 14초 | 위와 같은 오류 |

영상 링크 하나로 정리본까지 간 실측: 전사 57초 → 색인 5,896토큰(1회) →
정리본 2,449토큰, 7쪽 PDF, 한국어 이탈 0%.

## 공개 배포

`UNIFI_PASSWORD` 를 설정하면 사이트 전체에 비밀번호 게이트가 걸린다. 비워 두면
게이트가 아예 꺼지므로 **로컬에서만** 비워 둔다.

```bash
# /home/claude/.config/unifi-site/env  (chmod 600)
UNIFI_PASSWORD=<긴 랜덤 문자열>
UNIFI_DATA_DIR=/home/claude/unifi-site/data
UNIFI_PORT=8090
```

`deploy/` 에 systemd 유저 유닛 두 개가 있다. 서비스는 루프백에만 바인딩하고,
바깥 노출은 터널이 담당한다.

```bash
cp deploy/unifi-site.service deploy/unifi-tunnel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now unifi-site.service unifi-tunnel.service
cat ~/.config/unifi-site/public-url        # 현재 공개 주소
```

공개 모드에서는 로컬 PC 에이전트용 **에이전트 토큰이 필수**다. 에이전트 엔드포인트는
쿠키가 없어 비밀번호 게이트를 지나가므로, 토큰이 비어 있으면 서버가 503 으로 거절한다.
웹의 "알림 설정 → 에이전트 토큰" 에 값을 넣고 에이전트에도 같은 값을 준다.

### 고정 도메인

`deploy/tunnel.sh` 가 쓰는 Cloudflare quick tunnel 은 주소가 재시작마다 바뀐다.
주소를 고정하려면 둘 중 하나로 바꾼다.

- **Cloudflare named tunnel** — 도메인 DNS 를 Cloudflare 로 옮긴 뒤
  `cloudflared tunnel create unifi` + `cloudflared tunnel route dns unifi unifi.<도메인>`.
  Cloudflare Access 를 얹으면 비밀번호 대신 구글 로그인으로 바꿀 수도 있다.
- **기존 리버스 프록시에 추가** — 이미 TLS 를 끝내는 프록시가 있으면
  `unifi.<도메인>` A 레코드를 추가하고 `→ <이 서버>:8090` 으로 프록시한다.
  이때 `X-Forwarded-Proto: https` 를 넘겨야 세션 쿠키에 Secure 가 붙는다.

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
