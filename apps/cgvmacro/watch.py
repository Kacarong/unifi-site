"""서버 쪽 감시 루프 — CGV 무인증 API 폴링 → 이벤트 기록 + 디스코드 알림.

브라우저/로그인이 필요 없으므로 통합 사이트 서버에서 계속 돌 수 있다.
실제 좌석 선점(로그인 크롬 조작)은 여기서 하지 않고, `auto_grab` 이 켜진
대상이면 선점 작업(job)만 만들어 두고 로컬 PC 에이전트가 가져가게 한다.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

from . import store
from .core import cgv_api
from .core.cgv_api import CgvApiError, CgvRateLimited, Showtime
from .core.notifier import DiscordNotifier

log = logging.getLogger("unifi.cgvmacro")

BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/movie"


def _scnymd(date: str) -> str:
    return date.replace("-", "").replace(".", "").strip()


def _status_of(s: Showtime, min_remaining: int) -> str:
    if s.controlled or s.soldout or s.remaining == 0:
        return "soldout"
    if s.remaining >= min_remaining:
        return "available"
    return "open"


def _status_text(s: Showtime) -> str:
    if s.controlled:
        return "판매통제"
    if s.soldout or s.remaining == 0:
        return "매진"
    total = f"/{s.total}" if s.total > 0 else ""
    return f"잔여 {s.remaining}{total}석"


def _in_range(s: Showtime, time_from: str, time_to: str) -> bool:
    if time_from and s.time < time_from:
        return False
    if time_to and s.time > time_to:
        return False
    return True


def _kinds_for(is_new: bool, prev: str, cur: str, alerts: dict[str, Any]) -> list[str]:
    kinds: list[str] = []
    if is_new and alerts.get("on_showtime_open", True):
        kinds.append("open")
    if cur == "available":
        if prev == "soldout" and alerts.get("on_soldout_to_available", True):
            kinds.append("cancel")
        elif prev != "available" and alerts.get("on_seats_available", True):
            kinds.append("available")
    return kinds


class Watcher:
    """감시 스레드 하나로 모든 대상을 순회한다."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.last_poll_at: float = 0.0
        self.last_error: str = ""
        self.poll_count: int = 0
        self._codes: dict[str, tuple[str, str]] = {}  # 캐시: 영화/극장 코드 해석

    # ---------- 제어 ----------
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive()) and not self._stop.is_set()

    def start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="cgv-watcher", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self.running:
                return False
            self._stop.set()
            return True

    def status(self) -> dict[str, Any]:
        targets = store.list_targets()
        return {
            "running": self.running,
            "last_poll_at": self.last_poll_at,
            "last_error": self.last_error,
            "poll_count": self.poll_count,
            "targets_enabled": sum(1 for t in targets if t.get("enabled")),
            "targets_total": len(targets),
        }

    # ---------- 내부 ----------
    def _notifier(self) -> DiscordNotifier | None:
        settings = store.get_settings()
        url = settings.get("discord_webhook_url") or ""
        if not url:
            return None
        return DiscordNotifier(webhook_url=url, mention=settings.get("discord_mention", ""))

    def _resolve(self, target: dict[str, Any]) -> tuple[str, str, str, str]:
        """(mov_no, mov_nm, site_no, site_nm) — 결과를 캐시한다."""
        key = "|".join(
            [
                target.get("movie", ""),
                target.get("movie_code", ""),
                target.get("theater", ""),
                target.get("theater_code", ""),
            ]
        )
        cached = self._codes.get(key)
        if cached:
            return cached  # type: ignore[return-value]

        mov_no, mov_nm = cgv_api.resolve_movie(target.get("movie", ""), target.get("movie_code", ""))
        site_no, site_nm, _region = cgv_api.resolve_theater(
            target.get("theater", ""), target.get("theater_code", "")
        )
        resolved = (mov_no, mov_nm, site_no, site_nm)
        self._codes[key] = resolved  # type: ignore[assignment]
        return resolved

    def _poll_target(self, target: dict[str, Any], notifier: DiscordNotifier | None) -> None:
        alerts = target.get("alerts", store.DEFAULT_ALERTS)
        min_remaining = int(alerts.get("min_remaining_seats", 1))

        mov_no, mov_nm, site_no, site_nm = self._resolve(target)
        showtimes = cgv_api.fetch_showtimes(mov_no, site_no, _scnymd(target.get("date", "")))

        screen_type = (target.get("screen_type") or "").strip()
        seen: dict[str, str] = dict(target.get("seen") or {})
        next_seen: dict[str, str] = {}
        # 첫 관측은 기준선만 잡는다. 이미 열려 있던 회차까지 "오픈/잔여석"으로
        # 알리면 등록하자마자 알림과 선점 작업이 쏟아진다.
        baseline = not target.get("baselined")

        for s in showtimes:
            if not _in_range(s, target.get("time_from", ""), target.get("time_to", "")):
                continue
            if screen_type and screen_type.upper() not in f"{s.fmt} {s.screen}".upper():
                continue

            key = s.showtime_key()
            cur = _status_of(s, min_remaining)
            prev = seen.get(key, "")
            next_seen[key] = cur

            if baseline:
                continue

            kinds = _kinds_for(is_new=key not in seen, prev=prev, cur=cur, alerts=alerts)

            if alerts.get("on_stage_event") and cgv_api.stage_event_label(s.raw):
                kinds.append("stage_event")

            for kind in kinds:
                self._emit(target, s, kind, mov_nm, site_nm, notifier)

            if target.get("auto_grab") and cur == "available" and ("cancel" in kinds or "available" in kinds):
                self._queue_grab(target, s)

        store.set_seen(target["id"], next_seen)
        if baseline:
            store.update_target(target["id"], {"baselined": True})
            log.info("[%s] 기준선 %d개 회차 기록 — 다음 변화부터 알립니다", target.get("name"), len(next_seen))

    def _queue_grab(self, target: dict[str, Any], s: Showtime) -> None:
        """같은 회차에 대기 중인 작업이 이미 있으면 새로 만들지 않는다."""
        pending = {
            (job.get("target_id"), (job.get("showtime") or {}).get("schedule_key"))
            for job in store.list_jobs(limit=store.MAX_JOBS)
            if job.get("status") in ("queued", "claimed", "running")
        }
        key = s.showtime_key()
        if (target["id"], key) in pending:
            return

        store.create_job(
            target,
            {
                "time": s.time,
                "screen": s.screen,
                "fmt": s.fmt,
                "remaining": s.remaining,
                "schedule_id": s.schedule_id,
                "scns_no": s.scns_no,
                "schedule_key": key,
            },
            reason="auto_grab",
        )

    def _emit(
        self,
        target: dict[str, Any],
        s: Showtime,
        kind: str,
        movie: str,
        theater: str,
        notifier: DiscordNotifier | None,
    ) -> None:
        store.add_event(
            {
                "kind": kind,
                "target_id": target["id"],
                "target_name": target.get("name", ""),
                "movie": movie,
                "theater": theater,
                "date": target.get("date", ""),
                "time": s.time,
                "screen": s.screen,
                "status_text": _status_text(s),
            }
        )
        if notifier:
            try:
                notifier.notify_showtime(
                    kind=kind,
                    target_name=target.get("name", ""),
                    movie=movie,
                    theater=theater,
                    date=target.get("date", ""),
                    showtime=s.time,
                    status_text=_status_text(s),
                    booking_url=BOOKING_URL,
                    screen=s.screen,
                )
            except Exception as exc:  # noqa: BLE001 - 알림 실패가 감시를 멈추면 안 된다
                log.warning("디스코드 알림 실패: %s", exc)

    def _loop(self) -> None:
        log.info("CGV 감시 시작")
        backoff = 0
        while not self._stop.is_set():
            settings = store.get_settings()
            notifier = self._notifier()
            try:
                for target in store.list_targets():
                    if self._stop.is_set():
                        break
                    if not target.get("enabled"):
                        continue
                    try:
                        self._poll_target(target, notifier)
                    except CgvRateLimited as exc:
                        backoff = min(backoff + 30, 300)
                        self.last_error = f"요청 과다: {exc}"
                        log.warning("%s — %ds 백오프", self.last_error, backoff)
                    except CgvApiError as exc:
                        self.last_error = f"[{target.get('name')}] {exc}"
                        log.warning("감시 오류: %s", self.last_error)
                    else:
                        backoff = 0
                        self.last_error = ""
                self.last_poll_at = time.time()
                self.poll_count += 1
            except Exception as exc:  # noqa: BLE001 - 루프는 절대 죽지 않는다
                self.last_error = str(exc)
                log.exception("감시 루프 예외")

            interval = max(10, int(settings.get("poll_interval_seconds", 45)))
            jitter = random.uniform(0, max(0, int(settings.get("jitter_seconds", 15))))
            self._stop.wait(interval + jitter + backoff)
        log.info("CGV 감시 중지")


watcher = Watcher()
