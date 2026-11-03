"""정상 작동 점검과 자동 복구 (15분마다).

unifi 안에서는(cfg.in_process) 웹·터널·타이머 점검을 건너뛴다. 그건 unifi-site.service 가 맡는다.
남는 것은 수집이 멈췄는지(멈췄으면 그 자리에서 한 번 수집)와 봇 토큰이다.
아래는 따로 띄워 돌리던 때의 전체 점검 항목이다.

점검 항목과 복구:
- 유닛(web, tunnel, collect.timer)이 active인지 -> 아니면 restart 후 다시 확인
- 로컬 웹 /api/health -> 실패하면 web 재시작 후 다시 확인
- 공개 주소 /api/health (PUBLIC_URL이 있을 때) -> 실패하면 tunnel 재시작 후 다시 확인
- 마지막 수집 시각이 수집 간격(긴 쪽)의 3배보다 오래됨 -> 타이머 재시작 + 수집 1회 실행 후 다시 확인
- 봇 토큰 유효(GET /users/@me) -> 자동 복구 불가, 알림만 (웹훅이 있으면 웹훅으로)

알림: 복구에 실패한 항목만, 같은 장애는 한 번만 알리고, 풀리면 '복구됨'을 한 번 보낸다.
하루 한 번(기본 09시) '정상 작동 중' 요약을 보낸다. 이 요약이 안 오면 점검 자체가 멈췄다는 뜻이다.
"""
from __future__ import annotations

import logging
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from typing import Any, Callable

import httpx

from . import db, notifier, pipeline
from .config import Config

log = logging.getLogger(__name__)

WEB_UNIT = "housing-alert-web.service"
TUNNEL_UNIT = "housing-alert-tunnel.service"
TIMER_UNIT = "housing-alert-collect.timer"
COLLECT_UNIT = "housing-alert-collect.service"
UNITS = [WEB_UNIT, TUNNEL_UNIT, TIMER_UNIT]
STALE_FACTOR = 3
DEFAULT_REPORT = {"enabled": False, "hour": 9}  # 기본은 끔: 장애·복구 때만 알린다
LABELS = {
    "unit:" + WEB_UNIT: "웹 서비스", "unit:" + TUNNEL_UNIT: "공개 터널", "unit:" + TIMER_UNIT: "수집 타이머",
    "web": "웹 응답(로컬)", "public": "공개 주소 응답", "collect": "수집 실행", "bot": "디스코드 봇 토큰",
}

Runner = Callable[[list[str]], tuple[int, str]]


def systemctl(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=1200)
    return p.returncode, (p.stdout or "").strip()


def get_report_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    out = dict(DEFAULT_REPORT)
    out.update({k: v for k, v in (db.get_setting(conn, "daily_report") or {}).items() if k in out})
    return out


class Checker:
    def __init__(self, conn: sqlite3.Connection, cfg: Config, *, run: Runner = systemctl,
                 client: httpx.Client | None = None, sleep=time.sleep, now: datetime | None = None,
                 wait_seconds: int = 30, collect_now: Callable[[], None] | None = None) -> None:
        self.conn, self.cfg, self.run, self.sleep = conn, cfg, run, sleep
        self.collect_now = collect_now  # 있으면 systemd 대신 이걸로 수집을 다시 돌린다
        self.client = client or httpx.Client(timeout=15)
        self.now = now or pipeline.now_kst()
        self.wait_seconds = wait_seconds
        self.results: dict[str, dict[str, Any]] = {}
        self.recovered: list[str] = []  # 이번 실행에서 자동 복구한 항목

    # ------------------------------------------------------------ 기본 동작
    def _record(self, key: str, ok: bool, detail: str = "") -> bool:
        self.results[key] = {"ok": ok, "detail": detail}
        return ok

    def unit_exists(self, unit: str) -> bool:
        """설치하고 켜 둔(enabled) 유닛만 점검한다. 터널을 안 쓰는 서버에서는 건너뛴다."""
        return self.run(["is-enabled", unit])[1] == "enabled"

    def unit_active(self, unit: str) -> bool:
        return self.run(["is-active", unit])[1] == "active"

    def restart(self, unit: str) -> None:
        self.run(["reset-failed", unit])
        self.run(["restart", unit])

    def http_ok(self, url: str) -> bool:
        try:
            return self.client.get(url, timeout=10).status_code == 200
        except httpx.HTTPError:
            return False

    def wait_until(self, fn: Callable[[], bool]) -> bool:
        for _ in range(max(self.wait_seconds // 5, 1)):
            self.sleep(5)
            if fn():
                return True
        return False

    def _attempt(self, key: str, ok_fn: Callable[[], bool], fix: Callable[[], None], what: str) -> bool:
        if ok_fn():
            return self._record(key, True)
        fix()
        if self.wait_until(ok_fn):
            self.recovered.append(key)
            return self._record(key, True, f"{what} 후 정상")
        return self._record(key, False, f"{what} 후에도 실패")

    # ------------------------------------------------------------ 점검 항목
    def check_units(self) -> None:
        for unit in UNITS:
            if not self.unit_exists(unit):
                continue
            self._attempt("unit:" + unit, lambda u=unit: self.unit_active(u), lambda u=unit: self.restart(u), "재시작")

    def check_web(self) -> None:
        url = f"http://127.0.0.1:{self.cfg.port}{self.cfg.base_path}/api/health"
        ok = lambda: self.http_ok(url)  # noqa: E731
        if not ok():
            self.sleep(5)  # 순간 오류 한 번은 넘어간다
        self._attempt("web", ok, lambda: self.restart(WEB_UNIT), "웹 재시작")

    def check_public(self) -> None:
        if not self.cfg.public_url:
            return
        if not self.results.get("web", {}).get("ok"):
            return  # 로컬 웹이 죽었으면 공개 주소도 당연히 실패하므로 따로 알리지 않는다
        url = self.cfg.public_url.rstrip("/") + "/api/health"
        ok = lambda: self.http_ok(url)  # noqa: E731
        if not ok():
            self.sleep(5)
        if not self.unit_exists(TUNNEL_UNIT):
            self._record("public", ok(), "")
            return
        self._attempt("public", ok, lambda: self.restart(TUNNEL_UNIT), "터널 재시작")

    def stale_minutes(self) -> int:
        sch = pipeline.get_schedule(self.conn)
        return STALE_FACTOR * max(sch["day_interval_min"], sch["night_interval_min"])

    def collect_fresh(self) -> bool:
        last = db.get_setting(self.conn, "last_collect_at")
        if not last:
            return False
        return self.now - datetime.fromisoformat(last) <= timedelta(minutes=self.stale_minutes())

    def check_collect(self) -> None:
        if self.collect_fresh() or pipeline.is_running(self.cfg):
            self._record("collect", True)
            return

        def fix() -> None:
            if self.collect_now:
                self.collect_now()  # 끝날 때까지 기다린다
                return
            self.restart(TIMER_UNIT)
            self.run(["reset-failed", COLLECT_UNIT])
            self.run(["start", COLLECT_UNIT])  # oneshot이라 수집이 끝날 때까지 기다린다

        def fresh() -> bool:
            self.now = pipeline.now_kst()
            return self.collect_fresh()

        fix()
        if fresh():
            self.recovered.append("collect")
            self._record("collect", True, "수집 다시 실행 후 정상")
        else:
            last = db.get_setting(self.conn, "last_collect_at") or "없음"
            self._record("collect", False, f"마지막 수집 {last[:16].replace('T', ' ')}, 다시 실행해도 갱신 안 됨")

    def check_bot(self) -> None:
        token = db.get_setting(self.conn, "bot_token")
        if not token:
            return
        headers = {"Authorization": f"Bot {token}", "User-Agent": "DiscordBot (housing-alert, 1.0)"}
        detail = ""
        for attempt in range(2):  # 순간 오류 한 번은 넘어간다
            if attempt:
                self.sleep(5)
            try:
                resp = self.client.get(f"{notifier.DISCORD_API}/users/@me", timeout=10, headers=headers)
            except httpx.HTTPError as exc:
                detail = f"디스코드 연결 실패({type(exc).__name__})"
                continue
            if resp.status_code == 200:
                self._record("bot", True, "HTTP 200")
                return
            if resp.status_code == 401:
                self._record("bot", False, "토큰이 무효입니다(401). 설정 화면에서 새 토큰을 넣어 주세요")
                return
            detail = f"디스코드 응답 HTTP {resp.status_code}"
        self._record("bot", False, detail)

    def run_all(self) -> dict[str, dict[str, Any]]:
        if not self.cfg.in_process:  # 따로 띄운 웹 서버가 있을 때만
            self.check_units()
            self.check_web()
            self.check_public()
        self.check_collect()
        self.check_bot()
        return self.results


# ------------------------------------------------------------------ 알림

def _alert_sender(conn: sqlite3.Connection, cfg: Config, results: dict) -> Callable[..., None] | None:
    """봇 점검이 실패했으면(토큰 무효·디스코드 오류) DM 대신 웹훅으로 보낸다."""
    if results.get("bot", {}).get("ok") is False:
        url = notifier.get_webhook(conn, cfg)
        return notifier.webhook_sender(url) if url else None
    return notifier.get_sender(conn, cfg)


def _fmt_time(iso: str | None) -> str:
    return iso[:16].replace("T", " ") if iso else "없음"


def daily_summary(conn: sqlite3.Connection, results: dict, now: datetime, recoveries: int) -> str:
    since = (now - timedelta(hours=24)).isoformat()
    new = conn.execute("SELECT COUNT(*) FROM notices WHERE first_seen_at>=? AND baseline=0", (since,)).fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM notifications WHERE status='sent' AND sent_at>=?", (since,)).fetchone()[0]
    runs = conn.execute("SELECT COUNT(*) FROM runs WHERE started_at>=? AND finished_at IS NOT NULL", (since,)).fetchone()[0]
    bad = [f"{LABELS.get(k, k)}: {v['detail']}" for k, v in results.items() if not v["ok"]]
    lines = [
        "✅ housing-alert 정상 작동 중" if not bad else "⚠️ housing-alert 일부 이상",
        f"마지막 수집: {_fmt_time(db.get_setting(conn, 'last_collect_at'))}",
        f"최근 24시간: 수집 {runs}회, 새 공고 {new}건, 보낸 알림 {sent}건, 자동 복구 {recoveries}회",
        "점검: " + ", ".join(f"{LABELS.get(k, k)} {'정상' if v['ok'] else '이상'}" for k, v in results.items()),
    ]
    lines += bad
    lines.append("이 메시지가 하루 넘게 안 오면 점검 기능이 멈춘 것입니다.")
    return "\n".join(lines)


def run_healthcheck(conn: sqlite3.Connection, cfg: Config, **kw: Any) -> dict[str, Any]:
    send_client: httpx.Client | None = kw.pop("send_client", None)
    sleep = kw.get("sleep", time.sleep)
    checker = Checker(conn, cfg, **kw)
    results = checker.run_all()
    now = checker.now
    state: dict[str, Any] = db.get_setting(conn, "health_state") or {}
    issues: dict[str, Any] = state.get("issues", {})
    recoveries = int(state.get("recoveries", 0)) + len(checker.recovered)

    # issues: 지금 실패 중인 항목(알림 성공 여부와 무관하게 기록), alerted: 장애 알림을 보냈는지
    for k, v in results.items():
        if not v["ok"]:
            issues.setdefault(k, {"since": now.isoformat(), "alerted": False})["detail"] = v["detail"]
    for k in [k for k in issues if results.get(k, {}).get("ok") is True and not issues[k].get("alerted")]:
        issues.pop(k)  # 알리기 전에 풀린 장애는 조용히 지운다
    new_bad = [k for k, v in issues.items() if not v.get("alerted") and results.get(k, {}).get("ok") is False]
    healed = [k for k, v in issues.items() if v.get("alerted") and results.get(k, {}).get("ok") is True]

    report = get_report_settings(conn)
    today = now.date().isoformat()
    report_due = report["enabled"] and now.hour >= int(report["hour"]) and state.get("last_report") != today

    outbox: list[tuple[str, str]] = []
    if new_bad:
        outbox.append(("alert", "🚨 housing-alert 장애 (자동 복구 실패)\n" + "\n".join(
            f"- {LABELS.get(k, k)}: {results[k]['detail']}" for k in new_bad)))
    if healed:
        outbox.append(("healed", "✅ housing-alert 복구됨\n" + "\n".join(f"- {LABELS.get(k, k)}" for k in healed)))
    if report_due:
        outbox.append(("report", daily_summary(conn, results, now, recoveries)))

    delivered: set[str] = set()
    if outbox:
        sender = _alert_sender(conn, cfg, results)
        if sender is None:
            log.warning("알림 보낼 곳이 없습니다(봇 토큰 무효이고 웹훅 없음)")
        else:
            own = send_client is None
            client = send_client or httpx.Client()
            try:
                for kind, text in outbox:
                    try:
                        notifier.send_text(client, sender, text, sleep=sleep)
                        delivered.add(kind)
                    except notifier.WebhookError as exc:
                        log.warning("점검 알림 전송 실패: %s", exc)
            finally:
                if own:
                    client.close()

    # 못 보낸 알림은 다음 점검 때 다시 보낸다
    if "alert" in delivered:
        for k in new_bad:
            issues[k]["alerted"] = True
    if "healed" in delivered:
        for k in healed:
            issues.pop(k, None)
    if "report" in delivered:
        state["last_report"] = today
        recoveries = 0
    state.update({"issues": issues, "recoveries": recoveries, "last_check_at": now.isoformat(),
                  "last_results": results})
    db.set_setting(conn, "health_state", state)
    return {"results": results, "recovered": checker.recovered,
            "alerted": new_bad if "alert" in delivered else [], "unsent_alerts": [] if "alert" in delivered else new_bad,
            "healed": healed if "healed" in delivered else [], "report_sent": "report" in delivered,
            "messages_sent": bool(delivered)}
