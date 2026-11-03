"""설정.

unifi 안에서는 `.env` 대신 unifi 의 데이터 폴더(`data/housing/`)를 쓴다.
비밀값(봇 토큰, 웹훅, 공공데이터포털 키)은 DB settings 테이블에 저장되고, 웹 설정 화면에서 바꾼다.
환경변수 `HA_DATA_GO_KR_KEY`·`HA_DISCORD_WEBHOOK_URL` 은 DB 값이 없을 때만 쓰인다.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
APP_ROOT = Path(__file__).resolve().parent.parent  # apps/housing
BASE_PATH = "/apps/housing"


@dataclass
class Config:
    root: Path
    data_dir: Path
    db_path: Path
    host: str
    port: int
    base_path: str
    session_secret: str
    data_go_kr_key: str
    discord_webhook_url: str
    http_delay: float
    public_url: str = ""
    # 통합 사이트(unifi) 안에서 돈다: 따로 띄운 웹·터널·타이머가 없으니 그 점검은 건너뛴다
    in_process: bool = False


def _session_secret(data_dir: Path) -> str:
    """폼 CSRF 서명용 비밀값. 재시작해도 열려 있던 화면의 폼이 깨지지 않게 파일로 남긴다."""
    path = data_dir / "session_secret"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    return value


def load_config() -> Config:
    from server.paths import data_dir

    data = Path(data_dir("housing"))
    return Config(
        root=APP_ROOT,
        data_dir=data,
        db_path=data / "housing_alert.db",
        host="127.0.0.1",
        port=0,
        base_path=BASE_PATH,
        session_secret=_session_secret(data),
        data_go_kr_key=os.environ.get("HA_DATA_GO_KR_KEY", ""),
        discord_webhook_url=os.environ.get("HA_DISCORD_WEBHOOK_URL", ""),
        http_delay=float(os.environ.get("HA_HTTP_DELAY", "2.0")),
        in_process=True,
    )
