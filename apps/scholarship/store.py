"""장학금 알리미의 저장소.

- `items.json`  최근에 받은 장학금 목록 (원본 CSV 를 정리한 것)
- `extras.json` CSV 에 아직 없는 장학금 — 한국장학재단 실시간 포털·드림스폰·공고 게시판에서 모은 것
- `kosaf_cache.json` 포털 상세를 이미 받아 둔 것 (갱신마다 다시 받지 않게)
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
EXTRAS_PATH = os.path.join(DIR, "extras.json")
KOSAF_CACHE_PATH = os.path.join(DIR, "kosaf_cache.json")
STATE_PATH = os.path.join(DIR, "state.json")

DEFAULT_PROFILE: dict[str, Any] = {
    "regions": "",   # 쉼표로 구분한 지역 낱말 — "부산, 해운대구"
    "level": "",     # "" | 신입생 | 재학생 | 대학원
    "school": "",    # "" | SCHOOL_VOCAB 중 하나
    "field": "",     # "" | FIELD_VOCAB 중 하나
    "purpose": "",   # "" | living(생활비라고 적힌 것만) | no_tuition(등록금 전용만 빼기)
    "exclude_loans": True,  # 학자금 대출·대출이자 지원은 장학금이 아니다
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "discord_bot_token": "",    # 봇 토큰 — 화면에 다시 내보내지 않는다
    "discord_channel_id": "",   # 알림을 올릴 채널 ID
    "discord_mention": "",
    "notify_new": True,         # 내 조건에 맞는 새 장학금이 올라오면
    "notify_starred": True,     # 관심 장학금의 새 회차·마감 임박
    "reminder_days": [7, 3, 1],
}

MAX_SENT = 2000

_lock = threading.RLock()
_state: dict[str, Any] | None = None
_items: list[dict[str, Any]] | None = None   # CSV + extras 를 합친 것
_base: list[dict[str, Any]] | None = None    # CSV
_extras: list[dict[str, Any]] | None = None


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
        "last_extra_at": 0.0,  # 포털·게시판 확인
        "extra_error": "",
        "sources_off": [],      # 끈 게시판 id
        "custom_sources": [],   # 사용자가 더한 게시판 {id, label, url, loose}
        "source_stats": {},     # 게시판 id → 마지막 확인 결과
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
            # 예전 웹훅 주소처럼 이제 안 쓰는 설정은 버린다
            old = loaded.get("settings", {})
            state["settings"] = {**DEFAULT_SETTINGS, **{k: v for k, v in old.items() if k in DEFAULT_SETTINGS}}
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
def _read_list(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _merged() -> list[dict[str, Any]]:
    global _items, _base, _extras
    if _base is None:
        _base = _read_list(ITEMS_PATH)
    if _extras is None:
        _extras = _read_list(EXTRAS_PATH)
    if _items is None:
        from .logic import merge

        _items = merge(_base, _extras)
    return _items


def items() -> list[dict[str, Any]]:
    with _lock:
        return _merged()


def base_items() -> list[dict[str, Any]]:
    """CSV 에서 온 것만 — 포털에서 무엇이 새것인지 가릴 때 쓴다."""
    with _lock:
        _merged()
        return _base or []


def extra_items() -> list[dict[str, Any]]:
    """포털·게시판에서 모아 둔 것 그대로(합치기 전)."""
    with _lock:
        _merged()
        return list(_extras or [])


def replace_items(new_items: list[dict[str, Any]]) -> None:
    global _items, _base
    with _lock:
        _write(ITEMS_PATH, new_items)
        _base, _items = new_items, None


def replace_extras(new_extras: list[dict[str, Any]]) -> None:
    global _items, _extras
    with _lock:
        _write(EXTRAS_PATH, new_extras)
        _extras, _items = new_extras, None


def kosaf_cache() -> dict[str, Any]:
    try:
        with open(KOSAF_CACHE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_kosaf_cache(cache: dict[str, Any]) -> None:
    with _lock:
        _write(KOSAF_CACHE_PATH, cache)


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


# ---------------- 공고 게시판 출처 ----------------
def add_source(src: dict[str, Any]) -> None:
    with _lock:
        custom = _load()["custom_sources"]
        if not any(c["id"] == src["id"] for c in custom):
            custom.append(src)
        _save()


def remove_source(source_id: str) -> bool:
    with _lock:
        state = _load()
        before = len(state["custom_sources"])
        state["custom_sources"] = [c for c in state["custom_sources"] if c["id"] != source_id]
        state["source_stats"].pop(source_id, None)
        _save()
        return len(state["custom_sources"]) < before


def set_source_on(source_id: str, on: bool) -> None:
    with _lock:
        off = _load()["sources_off"]
        if on and source_id in off:
            off.remove(source_id)
        if not on and source_id not in off:
            off.append(source_id)
        _save()


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
