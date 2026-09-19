@echo off
REM unifi-site 실행 (윈도우)
cd /d "%~dp0"

if not exist .venv (
  echo 가상환경 생성 중...
  python -m venv .venv
  .venv\Scripts\pip install -q --upgrade pip
  .venv\Scripts\pip install -q -r requirements.txt
)

if "%UNIFI_PORT%"=="" set UNIFI_PORT=8000
echo http://localhost:%UNIFI_PORT% 에서 실행합니다.
.venv\Scripts\python -m uvicorn server.main:app --host 0.0.0.0 --port %UNIFI_PORT%
pause
