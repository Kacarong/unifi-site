"""cgv-macro 백엔드 라우터 (/api/cgvmacro/…).

역할 분담
  - 웹(이 서버): 감시 대상 설정, CGV API 폴링, 취소표/오픈 감지, 디스코드 알림
  - 로컬 PC 에이전트: 실제 좌석 선점(로그인된 크롬 조작). 서버에서 작업(job)을
    받아 가서 처리하고 결과를 돌려준다. `agent/README.md` 참고.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import store
from .core import cgv_api
from .watch import watcher

router = APIRouter()

_agents: dict[str, float] = {}  # agent_id -> 마지막 접속 시각


# ---------------- 모델 ----------------
class TargetIn(BaseModel):
    name: str = ""
    movie: str = ""
    movie_code: str = ""
    theater: str = ""
    theater_code: str = ""
    date: str = ""
    time_from: str = ""
    time_to: str = ""
    screen_type: str = ""
    enabled: bool = True
    auto_grab: bool = False
    alerts: Optional[dict[str, Any]] = None
    grab: Optional[dict[str, Any]] = None


class TargetPatch(BaseModel):
    name: Optional[str] = None
    movie: Optional[str] = None
    movie_code: Optional[str] = None
    theater: Optional[str] = None
    theater_code: Optional[str] = None
    date: Optional[str] = None
    time_from: Optional[str] = None
    time_to: Optional[str] = None
    screen_type: Optional[str] = None
    enabled: Optional[bool] = None
    auto_grab: Optional[bool] = None
    alerts: Optional[dict[str, Any]] = None
    grab: Optional[dict[str, Any]] = None


class SettingsPatch(BaseModel):
    poll_interval_seconds: Optional[int] = None
    jitter_seconds: Optional[int] = None
    discord_webhook_url: Optional[str] = None
    discord_mention: Optional[str] = None
    agent_token: Optional[str] = None


class GrabRequest(BaseModel):
    target_id: str
    showtime: dict[str, Any] = {}


class JobProgress(BaseModel):
    message: str = ""
    status: Optional[str] = None


class JobResult(BaseModel):
    status: str = "done"  # done | error
    result: Optional[dict[str, Any]] = None
    error: str = ""


# ---------------- 설정 ----------------
@router.get("/settings")
def get_settings() -> dict[str, Any]:
    settings = store.get_settings()
    settings["agent_token_set"] = bool(settings.pop("agent_token", ""))
    return settings


@router.patch("/settings")
def patch_settings(patch: SettingsPatch) -> dict[str, Any]:
    store.update_settings({k: v for k, v in patch.model_dump().items() if v is not None})
    return get_settings()


# ---------------- 감시 대상 ----------------
@router.get("/targets")
def list_targets() -> list[dict[str, Any]]:
    return store.list_targets()


@router.post("/targets")
def create_target(body: TargetIn) -> dict[str, Any]:
    return store.add_target(body.model_dump())


@router.patch("/targets/{target_id}")
def patch_target(target_id: str, body: TargetPatch) -> dict[str, Any]:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = store.update_target(target_id, patch)
    if not updated:
        raise HTTPException(404, "target not found")
    return updated


@router.delete("/targets/{target_id}")
def remove_target(target_id: str) -> dict[str, bool]:
    if not store.delete_target(target_id):
        raise HTTPException(404, "target not found")
    return {"ok": True}


# ---------------- CGV 조회(설정 화면용) ----------------
@router.get("/movies")
def movies() -> list[dict[str, str]]:
    try:
        return [{"code": code, "name": name} for code, name in cgv_api.list_movies()]
    except cgv_api.CgvApiError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/theaters")
def theaters() -> list[dict[str, str]]:
    try:
        return [
            {"code": code, "name": name, "region": region}
            for code, name, region in cgv_api.list_theaters()
        ]
    except cgv_api.CgvApiError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/showtimes")
def showtimes(movie: str = "", movie_code: str = "", theater: str = "",
              theater_code: str = "", date: str = "") -> list[dict[str, Any]]:
    """설정 화면에서 회차/잔여석을 즉시 확인하기 위한 단발 조회."""
    try:
        mov_no, _mov_nm = cgv_api.resolve_movie(movie, movie_code)
        site_no, _site_nm, _region = cgv_api.resolve_theater(theater, theater_code)
        found = cgv_api.fetch_showtimes(mov_no, site_no, date.replace("-", ""))
    except cgv_api.CgvApiError as exc:
        raise HTTPException(502, str(exc)) from exc

    return [
        {
            "time": s.time,
            "screen": s.screen,
            "fmt": s.fmt,
            "remaining": s.remaining,
            "total": s.total,
            "soldout": s.soldout,
            "controlled": s.controlled,
            "schedule_id": s.schedule_id,
            "scns_no": s.scns_no,
        }
        for s in found
    ]


# ---------------- 감시 제어 ----------------
@router.post("/monitor/start")
def monitor_start() -> dict[str, Any]:
    started = watcher.start()
    return {"started": started, **watcher.status()}


@router.post("/monitor/stop")
def monitor_stop() -> dict[str, Any]:
    stopped = watcher.stop()
    return {"stopped": stopped, **watcher.status()}


@router.get("/monitor/status")
def monitor_status() -> dict[str, Any]:
    status = watcher.status()
    status["agents"] = [
        {"id": agent_id, "last_seen": seen, "online": time.time() - seen < 30}
        for agent_id, seen in _agents.items()
    ]
    return status


@router.get("/events")
def events(limit: int = 50) -> list[dict[str, Any]]:
    return store.list_events(limit)


# ---------------- 선점 작업 ----------------
@router.get("/jobs")
def jobs(limit: int = 30) -> list[dict[str, Any]]:
    return store.list_jobs(limit)


@router.post("/jobs")
def request_grab(body: GrabRequest) -> dict[str, Any]:
    """웹에서 '지금 선점' 버튼을 누르면 로컬 에이전트가 가져갈 작업을 만든다."""
    target = store.get_target(body.target_id)
    if not target:
        raise HTTPException(404, "target not found")
    return store.create_job(target, body.showtime, reason="manual")


# ---------------- 로컬 에이전트 ----------------
def _check_agent(token: Optional[str]) -> None:
    expected = store.get_settings().get("agent_token") or ""
    if expected and token != expected:
        raise HTTPException(401, "invalid agent token")


@router.post("/agent/claim")
def agent_claim(
    agent_id: str = "local",
    x_agent_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """에이전트가 주기적으로 호출해 대기 중인 선점 작업을 가져간다."""
    _check_agent(x_agent_token)
    _agents[agent_id] = time.time()
    job = store.claim_job(agent_id)
    return {"job": job}


@router.post("/agent/jobs/{job_id}/progress")
def agent_progress(
    job_id: str,
    body: JobProgress,
    x_agent_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _check_agent(x_agent_token)
    patch: dict[str, Any] = {"message": body.message}
    if body.status:
        patch["status"] = body.status
    updated = store.update_job(job_id, patch)
    if not updated:
        raise HTTPException(404, "job not found")
    return updated


@router.post("/agent/jobs/{job_id}/result")
def agent_result(
    job_id: str,
    body: JobResult,
    x_agent_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _check_agent(x_agent_token)
    updated = store.update_job(
        job_id,
        {"status": body.status, "result": body.result, "error": body.error,
         "finished_at": time.time()},
    )
    if not updated:
        raise HTTPException(404, "job not found")

    store.add_event(
        {
            "kind": "seat_held" if body.status == "done" else "grab_error",
            "target_id": updated.get("target_id", ""),
            "target_name": updated.get("target_name", ""),
            "movie": updated.get("movie", ""),
            "theater": updated.get("theater", ""),
            "date": updated.get("date", ""),
            "time": (updated.get("showtime") or {}).get("time", ""),
            "screen": (updated.get("showtime") or {}).get("screen", ""),
            "status_text": body.error or "좌석 선점 완료",
        }
    )
    return updated
