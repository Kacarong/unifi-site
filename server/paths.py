"""앱들이 쓰는 데이터 저장 위치.

기본값은 레포 루트의 `data/<app_id>/`. `UNIFI_DATA_DIR` 로 덮어쓸 수 있다.
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("UNIFI_DATA_DIR") or os.path.join(ROOT, "data")


def data_dir(app_id: str, *sub: str) -> str:
    path = os.path.join(BASE, app_id, *sub)
    os.makedirs(path, exist_ok=True)
    return path
