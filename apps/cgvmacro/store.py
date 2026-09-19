"""cgv-macro 웹앱의 영속 상태 — 감시 대상 / 설정 / 이벤트 / 선점 작업.

전부 JSON 파일 하나(`data/cgvmacro/state.json`)에 저장한다. 개인용 규모라
DB 는 과하고, 파일 하나면 백업·수정이 쉽다.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any

from server.paths import data_dir

STATE_PATH = os.path.join(data_dir("cgvmacro"), "state.json")

DEFAULT_SETTINGS: dict[str, Any] = {
    "poll_interval_seconds": 45,
    "jitter_seconds": 15,
    "discord_webhook_url": "",
    "discord_mention": "",
    "agent_token": "",  # 비우면 로컬 에이전트 인증 없이 동작(같은 LAN 전제)
}

DEFAULT_ALERTS: dict[str, Any] = {
    "on_showtime_open": True,
    "on_seats_available": True,
    "on_soldout_to_available": True,
    "on_stage_event": False,
    "min_remaining_seats": 1,
}

DEFAULT_GRAB: dict[str, Any] = {
    "general": 2,
    "teen": 0,
    "senior": 0,
    "seats": "",
    "seats_only": False,
}

MAX_EVENTS = 200
MAX_JOBS = 100

_lock = threading.RLock()
_state: dict[str, Any] | None = None


def _blank() -> dict[str, Any]:
    return {"settings": dict(DEFAULT_SETTINGS), "targets": [], "events": [], "jobs": []}


def _load() -> dict[str, Any]:
    global _state
    if _state is not None:
        return _state
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as fh:
                loaded = json.load(fh)
            base = _blank()
            base.update(loaded)
            base["settings"] = {**DEFAULT_SETTINGS, **loaded.get("settings", {})}
            _state = base
        except (OSError, ValueError):
            _state = _blank()
    else:
        _state = _blank()
    return _state


def _save() -> None:
    state = _load()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


# ---------------- 설정 ----------------
def get_settings() -> dict[str, Any]:
    with _lock:
        return dict(_load()["settings"])


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        settings = _load()["settings"]
        settings.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS})
        _save()
        return dict(settings)


# ---------------- 감시 대상 ----------------
def list_targets() -> list[dict[str, Any]]:
    with _lock:
        return [dict(t) for t in _load()["targets"]]


def get_target(target_id: str) -> dict[str, Any] | None:
    with _lock:
        for t in _load()["targets"]:
            if t["id"] == target_id:
                return dict(t)
        return None


def add_target(data: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        target = {
            "id": uuid.uuid4().hex[:8],
            "name": data.get("name") or data.get("movie") or "새 감시",
            "movie": data.get("movie", ""),
            "movie_code": data.get("movie_code", ""),
            "theater": data.get("theater", ""),
            "theater_code": data.get("theater_code", ""),
            "date": data.get("date", ""),
            "time_from": data.get("time_from", ""),
            "time_to": data.get("time_to", ""),
            "screen_type": data.get("screen_type", ""),
            "enabled": bool(data.get("enabled", True)),
            "auto_grab": bool(data.get("auto_grab", False)),
            "alerts": {**DEFAULT_ALERTS, **(data.get("alerts") or {})},
            "grab": {**DEFAULT_GRAB, **(data.get("grab") or {})},
            "seen": {},  # showtime_key -> 마지막 상태
        }
        _load()["targets"].append(target)
        _save()
        return dict(target)


# 이 값들이 바뀌면 감시 대상 자체가 달라진 것이므로 기준선을 다시 잡는다.
IDENTITY_FIELDS = ("movie", "movie_code", "theater", "theater_code", "date",
                   "time_from", "time_to", "screen_type")


def update_target(target_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    with _lock:
        for t in _load()["targets"]:
            if t["id"] != target_id:
                continue
            if any(f in patch and patch[f] != t.get(f) for f in IDENTITY_FIELDS):
                t["seen"] = {}
                t["baselined"] = False
            for key, value in patch.items():
                if key in ("id", "seen"):
                    continue
                if key == "alerts":
                    t["alerts"] = {**t.get("alerts", DEFAULT_ALERTS), **(value or {})}
                elif key == "grab":
                    t["grab"] = {**t.get("grab", DEFAULT_GRAB), **(value or {})}
                else:
                    t[key] = value
            _save()
            return dict(t)
        return None


def delete_target(target_id: str) -> bool:
    with _lock:
        targets = _load()["targets"]
        before = len(targets)
        _load()["targets"] = [t for t in targets if t["id"] != target_id]
        changed = len(_load()["targets"]) != before
        if changed:
            _save()
        return changed


def set_seen(target_id: str, seen: dict[str, str]) -> None:
    with _lock:
        for t in _load()["targets"]:
            if t["id"] == target_id:
                t["seen"] = seen
                _save()
                return


# ---------------- 이벤트 로그 ----------------
def add_event(event: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        event = {"id": uuid.uuid4().hex[:8], "at": time.time(), **event}
        events = _load()["events"]
        events.insert(0, event)
        del events[MAX_EVENTS:]
        _save()
        return event


def list_events(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        return [dict(e) for e in _load()["events"][:limit]]


# ---------------- 선점 작업(로컬 에이전트가 가져감) ----------------
def create_job(target: dict[str, Any], showtime: dict[str, Any], reason: str = "") -> dict[str, Any]:
    with _lock:
        job = {
            "id": uuid.uuid4().hex[:10],
            "created_at": time.time(),
            "status": "queued",
            "reason": reason,
            "target_id": target["id"],
            "target_name": target.get("name", ""),
            "movie": target.get("movie", ""),
            "movie_code": target.get("movie_code", ""),
            "theater": target.get("theater", ""),
            "theater_code": target.get("theater_code", ""),
            "date": target.get("date", ""),
            "grab": target.get("grab", DEFAULT_GRAB),
            "showtime": showtime,
            "agent_id": "",
            "messages": [],
            "result": None,
            "error": "",
        }
        jobs = _load()["jobs"]
        jobs.insert(0, job)
        del jobs[MAX_JOBS:]
        _save()
        return dict(job)


def list_jobs(limit: int = 30) -> list[dict[str, Any]]:
    with _lock:
        return [dict(j) for j in _load()["jobs"][:limit]]


def claim_job(agent_id: str) -> dict[str, Any] | None:
    """가장 오래된 queued 작업 하나를 에이전트에게 넘긴다."""
    with _lock:
        for job in reversed(_load()["jobs"]):
            if job["status"] == "queued":
                job["status"] = "claimed"
                job["agent_id"] = agent_id
                job["claimed_at"] = time.time()
                _save()
                return dict(job)
        return None


def update_job(job_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    with _lock:
        for job in _load()["jobs"]:
            if job["id"] != job_id:
                continue
            message = patch.pop("message", None)
            if message:
                job["messages"].append({"at": time.time(), "text": message})
            job.update(patch)
            _save()
            return dict(job)
        return None
