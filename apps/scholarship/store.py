"""장학금 알리미의 저장소.

- `items.json`  최근에 받은 장학금 목록 (원본 CSV 를 정리한 것)
- `state.json`  내 조건, 관심 표시, 알림 설정, 이미 보낸 알림, 동기화 기록

개인용 규모라 파일 두 개면 충분하다. 목록은 크고(약 4MB) 자주 안 바뀌고,
상태는 작고 자주 바뀌어서 나눠 둔다.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from server.paths import data_dir

DIR = data_dir("scholarship")
ITEMS_PATH = os.path.join(DIR, "items.json")
STATE_PATH = os.path.join(DIR, "state.json")

DEFAULT_PROFILE: dict[str, Any] = {
    "regions": "",   # 쉼표로 구분한 지역 낱말 — "부산, 해운대구"
    "level": "",     # "" | 신입생 | 재학생 | 대학원
    "school": "",    # "" | SCHOOL_VOCAB 중 하나
    "field": "",     # "" | FIELD_VOCAB 중 하나
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "discord_webhook_url": "",
    "discord_mention": "",
    "notify_new": True,         # 내 조건에 맞는 새 장학금이 올라오면
    "notify_starred": True,     # 관심 장학금의 새 회차·마감 임박
    "reminder_days": [7, 3, 1],
}

MAX_SENT = 2000

_lock = threading.RLock()
_state: dict[str, Any] | None = None
_items: list[dict[str, Any]] | None = None


def _blank() -> dict[str, Any]:
    return {
        "profile": dict(DEFAULT_PROFILE),
        "settings": dict(DEFAULT_SETTINGS),
        "stars": [],        # series 목록
        "known_ids": [],    # 지금까지 본 회차 id — 새 장학금 판정용
        "baselined": False,
        "sent": [],         # 이미 보낸 알림 키
        "meta": {},         # 공공데이터포털 파일 번호·수정일
        "last_sync_at": 0.0,
        "last_check_at": 0.0,
        "last_error": "",    # 원본 갱신 실패
        "notify_error": "",  # 디스코드 전송 실패
        "site_url": "",      # 알림 메시지에 붙일 사이트 주소 (설정 저장할 때 기록)
    }


def _write(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _load() -> dict[str, Any]:
    global _state
    if _state is None:
        state = _blank()
        try:
            with open(STATE_PATH, encoding="utf-8") as fh:
                loaded = json.load(fh)
            state.update(loaded)
            state["profile"] = {**DEFAULT_PROFILE, **loaded.get("profile", {})}
            state["settings"] = {**DEFAULT_SETTINGS, **loaded.get("settings", {})}
        except (OSError, ValueError):
            pass
        _state = state
    return _state


def _save() -> None:
    _write(STATE_PATH, _load())


def snapshot() -> dict[str, Any]:
    with _lock:
        return json.loads(json.dumps(_load()))


def update(patch: dict[str, Any]) -> None:
    with _lock:
        _load().update(patch)
        _save()


# ---------------- 목록 ----------------
def items() -> list[dict[str, Any]]:
    global _items
    with _lock:
        if _items is None:
            try:
                with open(ITEMS_PATH, encoding="utf-8") as fh:
                    _items = json.load(fh)
            except (OSError, ValueError):
                _items = []
        return _items


def replace_items(new_items: list[dict[str, Any]]) -> None:
    global _items
    with _lock:
        _write(ITEMS_PATH, new_items)
        _items = new_items


# ---------------- 내 조건 / 설정 ----------------
def update_profile(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        profile = _load()["profile"]
        profile.update({k: v for k, v in patch.items() if k in DEFAULT_PROFILE})
        _save()
        return dict(profile)


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        settings = _load()["settings"]
        settings.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS})
        _save()
        return dict(settings)


# ---------------- 관심 ----------------
def set_star(series: str, on: bool) -> list[str]:
    with _lock:
        stars = _load()["stars"]
        if on and series not in stars:
            stars.append(series)
        if not on and series in stars:
            stars.remove(series)
        _save()
        return list(stars)


# ---------------- 보낸 알림 ----------------
def mark_sent(keys: list[str]) -> None:
    with _lock:
        sent = _load()["sent"]
        sent.extend(k for k in keys if k not in sent)
        del sent[:-MAX_SENT]
        _save()
