"""장학금 알리미 백엔드 (/api/scholarship/…)."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import logic, source, store
from .worker import build_message, now_kst, post_discord, sync, worker

router = APIRouter()

VIEWS = ("open", "year_round", "soon", "starred", "all")


class ProfilePatch(BaseModel):
    regions: Optional[str] = None
    level: Optional[str] = None
    school: Optional[str] = None
    field: Optional[str] = None
    purpose: Optional[str] = None
    exclude_loans: Optional[bool] = None


class SettingsPatch(BaseModel):
    discord_webhook_url: Optional[str] = None
    discord_mention: Optional[str] = None
    notify_new: Optional[bool] = None
    notify_starred: Optional[bool] = None
    reminder_days: Optional[list[int]] = None


class StarBody(BaseModel):
    on: bool = True


# ---------------- 상태 ----------------
@router.get("/status")
def status() -> dict[str, Any]:
    state = store.snapshot()
    items = store.items()
    today = now_kst().date()
    return {
        "count": len(items),
        "open": sum(1 for it in items if logic.status(it, today) == "open"),
        "meta": state["meta"],
        "source_page": source.PAGE_URL,
        "last_sync_at": state["last_sync_at"],
        "last_check_at": state["last_check_at"],
        "last_error": state["last_error"],
        "notify_error": state.get("notify_error", ""),
        "worker_running": worker.running,
        "notify_ready": bool(state["settings"].get("discord_webhook_url")),
        "stars": len(state["stars"]),
    }


@router.post("/sync")
def force_sync() -> dict[str, Any]:
    try:
        sync(force=True)
    except source.SourceError as exc:
        raise HTTPException(502, str(exc)) from exc
    return status()


@router.get("/options")
def options() -> dict[str, Any]:
    return {
        "levels": list(logic.LEVELS),
        "schools": [s for s in source.SCHOOL_VOCAB if s not in ("제한없음", "해당없음", "특정대학")],
        "fields": [f for f in source.FIELD_VOCAB if f not in ("제한없음", "해당없음", "특정학과")],
        "categories": sorted({it.get("category", "") for it in store.items()} - {""}),
    }


# ---------------- 내 조건 / 알림 설정 ----------------
@router.get("/profile")
def get_profile() -> dict[str, Any]:
    return store.snapshot()["profile"]


@router.patch("/profile")
def patch_profile(body: ProfilePatch) -> dict[str, Any]:
    patch = {k: v.strip() if isinstance(v, str) else v for k, v in body.model_dump().items() if v is not None}
    if patch.get("purpose") not in (None, "", "living", "no_tuition"):
        raise HTTPException(400, "purpose 는 '', living, no_tuition 중 하나")
    return store.update_profile(patch)


def _public_settings() -> dict[str, Any]:
    settings = store.snapshot()["settings"]
    url = settings.pop("discord_webhook_url", "")
    # 웹훅 주소는 그 자체가 비밀번호라 화면에 다시 내보내지 않는다.
    settings["discord_webhook_set"] = bool(url)
    return settings


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return _public_settings()


@router.patch("/settings")
def patch_settings(body: SettingsPatch, request: Request) -> dict[str, Any]:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    url = (patch.get("discord_webhook_url") or "").strip()
    if url and not url.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")):
        raise HTTPException(400, "디스코드 웹훅 주소가 아닙니다 (https://discord.com/api/webhooks/… 형태)")
    if "reminder_days" in patch:
        patch["reminder_days"] = sorted({d for d in patch["reminder_days"] if 0 <= d <= 60}, reverse=True)
    store.update_settings(patch)
    # 알림 메시지에서 사이트로 바로 오도록 지금 쓰고 있는 주소를 기억해 둔다.
    store.update({"site_url": str(request.base_url)})
    return _public_settings()


@router.post("/settings/test")
def test_notify() -> dict[str, bool]:
    state = store.snapshot()
    url = state["settings"].get("discord_webhook_url") or ""
    if not url:
        raise HTTPException(400, "디스코드 웹훅 주소를 먼저 저장해 주세요")
    today = now_kst().date()
    sample = [it for it in store.items() if logic.status(it, today) == "open"][:1]
    note = {"kind": "new", "items": sample, "keys": []}
    payload = build_message(note, state["settings"], state.get("site_url", ""), today)
    payload["embeds"][0]["title"] = "🔔 장학금 알리미 연결 확인 (테스트)"
    try:
        post_discord(url, payload)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}


# ---------------- 목록 ----------------
def _slim(it: dict[str, Any], today, stars: set[str], profile: dict[str, Any]) -> dict[str, Any]:
    support = [ln.lstrip("○ ").strip() for ln in (it.get("support") or "").splitlines() if ln.strip()]
    out = {
        k: it.get(k, "")
        for k in ("id", "series", "org", "name", "org_type", "category", "start", "end", "url",
                  "expected_start", "expected_end")
        if k in it
    }
    out.update(
        status=logic.status(it, today),
        dday=logic.dday(it, today),
        starred=it["series"] in stars,
        mine=logic.matches(profile, it),
        regional=logic.is_regional(it),
        region_check=logic.region_verdict(profile, it) == "unknown",
        purpose=logic.purpose(it),
        loan=logic.is_loan(it),
        support=" · ".join(support)[:140],
    )
    return out


def _search(items: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
    words = [w for w in q.split() if w]
    if not words:
        return items
    fields = ("org", "name", "support", "special", "region", "category")
    return [it for it in items if all(any(w in (it.get(f) or "") for f in fields) for w in words)]


def _view(view: str, items: list[dict[str, Any]], today, stars: set[str]) -> list[dict[str, Any]]:
    if view == "open":
        rows = [it for it in items if logic.status(it, today) == "open"]
        return sorted(rows, key=lambda it: it.get("end", ""))
    if view == "year_round":
        rows = [it for it in items if logic.status(it, today) == "year_round"]
        return sorted(rows, key=lambda it: it.get("end", ""))
    if view == "soon":
        return logic.forecast(items, today)
    if view == "starred":
        latest = logic.latest_rounds(it for it in items if it["series"] in stars)
        order = {"open": 0, "year_round": 1, "upcoming": 2, "closed": 3}
        return sorted(latest.values(), key=lambda it: (order[logic.status(it, today)], it.get("end", "")))
    return sorted(items, key=lambda it: it.get("start", ""), reverse=True)


@router.get("/items")
def list_items(view: str = "open", mine: bool = True, q: str = "", category: str = "",
               offset: int = 0, limit: int = 30) -> dict[str, Any]:
    if view not in VIEWS:
        raise HTTPException(400, f"view 는 {', '.join(VIEWS)} 중 하나")
    state = store.snapshot()
    profile, stars = state["profile"], set(state["stars"])
    today = now_kst().date()

    pool = _search(store.items(), q.strip())
    if category:
        pool = [it for it in pool if it.get("category") == category]
    if mine:
        # 관심 표시한 것은 지역·학년 조건과 상관없이 보인다. 대출·지원 용도로
        # 뺀 것은 관심이어도 뺀다 — '대출 제외' 라고 했는데 대출이 보이면 안 된다.
        pool = [
            it for it in pool
            if not logic.excluded(profile, it) and (it["series"] in stars or logic.matches(profile, it))
        ]

    counts = {v: len(_view(v, pool, today, stars)) for v in VIEWS}
    rows = _view(view, pool, today, stars)
    limit = max(1, min(limit, 100))
    page = rows[max(0, offset): max(0, offset) + limit]
    return {
        "total": len(rows),
        "counts": counts,
        "items": [_slim(it, today, stars, profile) for it in page],
    }


@router.get("/items/{item_id}")
def item_detail(item_id: str) -> dict[str, Any]:
    items = store.items()
    it = next((x for x in items if x["id"] == item_id), None)
    if not it:
        raise HTTPException(404, "장학금을 찾지 못했습니다")
    state = store.snapshot()
    today = now_kst().date()
    rounds = sorted(
        ({"id": x["id"], "start": x["start"], "end": x["end"]} for x in items if x["series"] == it["series"]),
        key=lambda r: r["start"],
        reverse=True,
    )
    # 목록용 요약(지원 내용 140자)이 원문을 덮지 않게 원문을 나중에 펼친다
    return {**_slim(it, today, set(state["stars"]), state["profile"]), **it, "rounds": rounds}


@router.put("/stars/{series}")
def star(series: str, body: StarBody) -> dict[str, Any]:
    if body.on and not any(it["series"] == series for it in store.items()):
        raise HTTPException(404, "장학금을 찾지 못했습니다")
    return {"stars": store.set_star(series, body.on)}
