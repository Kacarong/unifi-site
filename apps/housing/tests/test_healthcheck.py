"""정상 작동 점검: 유닛·웹·공개 주소·수집·봇 토큰, 자동 재시작, 중복 없는 장애 알림, 복구 알림, 일일 요약."""
import json
from dataclasses import replace
from datetime import datetime

import httpx
import pytest

from housing_alert import db, healthcheck
from housing_alert.config import KST

NOW = datetime(2026, 10, 17, 10, 0, tzinfo=KST)
HOOK = "https://discord.com/api/webhooks/123456789/abcdefTOKEN"


class FakeHost:
    """systemctl과 HTTP를 흉내낸다. broken: 재시작해도 안 살아나는 유닛."""

    def __init__(self):
        self.active = {u: True for u in healthcheck.UNITS}
        self.enabled = set(healthcheck.UNITS)
        self.broken: set[str] = set()
        self.calls: list[list[str]] = []
        self.bot_status = 200
        self.public_ok = True
        self.on_collect = None
        self.sent: list[dict] = []

    def run(self, args):
        self.calls.append(args)
        cmd, unit = args[0], args[-1]
        if cmd == "is-enabled":
            return 0, "enabled" if unit in self.enabled else "disabled"
        if cmd == "is-active":
            return 0, "active" if self.active.get(unit) else "inactive"
        if cmd == "restart":
            self.active[unit] = unit not in self.broken
            if unit == healthcheck.TUNNEL_UNIT and unit not in self.broken:
                self.public_ok = True
        if cmd == "start" and unit == healthcheck.COLLECT_UNIT and self.on_collect:
            self.on_collect()
        return 0, ""

    def handler(self, request):
        url = str(request.url)
        if "127.0.0.1" in url:
            return httpx.Response(200 if self.active[healthcheck.WEB_UNIT] else 502)
        if "housing.example" in url:
            return httpx.Response(200 if self.public_ok and self.active[healthcheck.WEB_UNIT] else 530)
        if url.endswith("/users/@me"):
            return httpx.Response(self.bot_status, json={"id": "1"})
        self.sent.append({"url": url, **json.loads(request.content)})
        if url.endswith("/users/@me/channels"):
            return httpx.Response(200, json={"id": "999"})
        return httpx.Response(200, json={"id": "1"})

    def restarts(self):
        return [c[-1] for c in self.calls if c[0] == "restart"]

    def texts(self):
        return [s["content"] for s in self.sent if "content" in s]


@pytest.fixture
def env(conn, cfg):
    cfg = replace(cfg, public_url="https://housing.example")
    host = FakeHost()
    client = httpx.Client(transport=httpx.MockTransport(lambda r: host.handler(r)))
    db.set_setting(conn, "bot_token", "x" * 60)
    db.set_setting(conn, "dm_user_id", "342251718551273473")
    db.set_setting(conn, "last_collect_at", "2026-10-17T09:30:00+09:00")
    db.set_setting(conn, "daily_report", {"enabled": False, "hour": 9})

    def check(now=NOW):
        return healthcheck.run_healthcheck(conn, cfg, run=host.run, client=client, send_client=client,
                                           sleep=lambda s: None, now=now, wait_seconds=10)

    return {"conn": conn, "host": host, "check": check, "cfg": cfg}


def test_all_ok_sends_nothing(env):
    out = env["check"]()
    assert all(v["ok"] for v in out["results"].values())
    assert set(out["results"]) == {"unit:" + u for u in healthcheck.UNITS} | {"web", "public", "collect", "bot"}
    assert env["host"].restarts() == [] and env["host"].sent == []


def test_dead_web_is_restarted_without_alert(env):
    env["host"].active[healthcheck.WEB_UNIT] = False
    out = env["check"]()
    assert env["host"].restarts() == [healthcheck.WEB_UNIT]
    assert out["results"]["web"]["ok"] and "unit:" + healthcheck.WEB_UNIT in out["recovered"]
    assert env["host"].sent == []  # 자동 복구에 성공하면 알리지 않는다


def test_public_down_restarts_tunnel(env):
    env["host"].public_ok = False
    out = env["check"]()
    assert env["host"].restarts() == [healthcheck.TUNNEL_UNIT]
    assert out["results"]["public"]["ok"] and out["recovered"] == ["public"]


def test_unrecoverable_failure_alerts_once_then_recovery(env):
    host = env["host"]
    host.active[healthcheck.WEB_UNIT] = False
    host.broken.add(healthcheck.WEB_UNIT)
    out = env["check"]()
    assert not out["results"]["web"]["ok"] and out["alerted"]
    assert "public" not in out["results"]  # 웹이 죽은 동안 공개 주소는 따로 알리지 않는다
    texts = host.texts()
    assert len(texts) == 1 and "장애" in texts[0] and "웹 서비스" in texts[0]
    # 같은 장애는 다시 알리지 않는다
    env["check"]()
    assert len(host.texts()) == 1
    # 풀리면 복구 알림 한 번
    host.broken.clear()
    host.active[healthcheck.WEB_UNIT] = True
    out = env["check"]()
    assert set(out["healed"]) == {"unit:" + healthcheck.WEB_UNIT, "web"}
    assert len(host.texts()) == 2 and "복구됨" in host.texts()[1]
    env["check"]()
    assert len(host.texts()) == 2


def test_stale_collect_restarts_timer_and_runs_collect(env):
    conn, host = env["conn"], env["host"]
    db.set_setting(conn, "last_collect_at", "2026-10-16T20:00:00+09:00")  # 14시간 전 (> 3 x 180분)
    host.on_collect = lambda: db.set_setting(conn, "last_collect_at", datetime.now(KST).isoformat())
    out = env["check"]()
    assert healthcheck.TIMER_UNIT in host.restarts()
    assert ["start", healthcheck.COLLECT_UNIT] in host.calls
    assert out["results"]["collect"]["ok"] and "collect" in out["recovered"]
    assert host.sent == []


def test_stale_collect_that_stays_stale_alerts(env):
    db.set_setting(env["conn"], "last_collect_at", "2026-10-16T20:00:00+09:00")
    out = env["check"]()
    assert not out["results"]["collect"]["ok"]
    assert "수집 실행" in env["host"].texts()[0]


def test_invalid_bot_token_alerts_via_webhook(env):
    conn, host = env["conn"], env["host"]
    host.bot_status = 401
    out = env["check"]()
    assert not out["results"]["bot"]["ok"]
    assert host.sent == []  # 웹훅이 없으면 보낼 곳이 없다
    # 알림은 못 보냈어도 장애 상태는 기록한다(설정 화면에 표시), 알림은 다음 점검 때 다시 시도
    issue = db.get_setting(conn, "health_state")["issues"]["bot"]
    assert issue["alerted"] is False and "401" in issue["detail"] and out["unsent_alerts"] == ["bot"]
    db.set_setting(conn, "webhook_url", HOOK)
    out = env["check"]()
    assert out["alerted"] == ["bot"]
    assert host.sent[-1]["url"].startswith(HOOK) and "토큰" in host.sent[-1]["content"]
    assert db.get_setting(conn, "health_state")["issues"]["bot"]["alerted"] is True
    env["check"]()
    assert len(host.texts()) == 1  # 한 번만


def test_daily_report_once_per_day(env):
    conn, host = env["conn"], env["host"]
    db.set_setting(conn, "daily_report", {"enabled": True, "hour": 9})
    env["check"](now=datetime(2026, 10, 17, 8, 45, tzinfo=KST).replace())
    assert host.sent == []  # 9시 전
    db.set_setting(conn, "last_collect_at", "2026-10-17T09:30:00+09:00")
    out = env["check"]()
    assert out["report_sent"] and "정상 작동 중" in host.texts()[0] and "마지막 수집: 2026-10-17 09:30" in host.texts()[0]
    env["check"](now=datetime(2026, 10, 17, 10, 15, tzinfo=KST))
    assert len(host.texts()) == 1
    db.set_setting(conn, "last_collect_at", "2026-10-18T09:00:00+09:00")
    env["check"](now=datetime(2026, 10, 18, 9, 15, tzinfo=KST))
    assert len(host.texts()) == 2


def test_daily_report_off_by_default(env):
    conn, host = env["conn"], env["host"]
    conn.execute("DELETE FROM settings WHERE key = 'daily_report'")
    out = env["check"](now=datetime(2026, 10, 17, 10, 15, tzinfo=KST))
    assert not out["report_sent"] and host.sent == []  # 정상이면 아무 DM도 없다


def test_disabled_tunnel_is_skipped(env):
    host = env["host"]
    host.enabled.discard(healthcheck.TUNNEL_UNIT)
    host.active[healthcheck.TUNNEL_UNIT] = False
    host.public_ok = False
    out = env["check"]()
    assert "unit:" + healthcheck.TUNNEL_UNIT not in out["results"]
    assert healthcheck.TUNNEL_UNIT not in host.restarts()
    assert not out["results"]["public"]["ok"]


def test_settings_page_shows_unsent_issue(env, cfg):
    from fastapi.testclient import TestClient
    from housing_alert.web.app import create_app
    conn, host = env["conn"], env["host"]
    host.bot_status = 401
    env["check"]()
    c = TestClient(create_app(cfg))
    html = c.get("/settings").text
    assert "장애 1건" in html and "알림 못 보냄" in html


@pytest.mark.parametrize("failure", ["503", "connect"])
def test_discord_outage_is_recorded_and_falls_back_to_webhook(env, failure):
    conn, host = env["conn"], env["host"]
    db.set_setting(conn, "webhook_url", HOOK)
    if failure == "503":
        host.bot_status = 503
    else:
        orig = host.handler

        def handler(request):
            if str(request.url).endswith("/users/@me"):
                raise httpx.ConnectError("boom")
            return orig(request)
        host.handler = handler
    out = env["check"]()
    assert out["results"]["bot"]["ok"] is False
    assert ("503" if failure == "503" else "연결 실패") in out["results"]["bot"]["detail"]
    assert out["alerted"] == ["bot"] and host.sent[-1]["url"].startswith(HOOK)


def test_transient_discord_error_is_retried(env):
    host = env["host"]
    statuses = [503, 200]
    orig = host.handler

    def handler(request):
        if str(request.url).endswith("/users/@me"):
            return httpx.Response(statuses.pop(0))
        return orig(request)
    host.handler = handler
    out = env["check"]()
    assert out["results"]["bot"]["ok"] and host.sent == []


def test_in_process_skips_units_and_collects_in_place(env):
    """unifi 안에서는 systemctl 을 부르지 않고, 수집이 멈췄으면 그 자리에서 한 번 수집한다."""
    conn, host = env["conn"], env["host"]
    cfg = replace(env["cfg"], in_process=True)
    db.set_setting(conn, "last_collect_at", "2026-10-16T10:00:00+09:00")  # 하루 전: 멈춤
    collected = []

    def collect_now():
        collected.append(1)
        db.set_setting(conn, "last_collect_at", healthcheck.pipeline.now_kst().isoformat())

    client = httpx.Client(transport=httpx.MockTransport(lambda r: host.handler(r)))
    out = healthcheck.run_healthcheck(conn, cfg, run=host.run, client=client, send_client=client,
                                      sleep=lambda s: None, now=NOW, wait_seconds=10, collect_now=collect_now)
    assert host.calls == []  # systemctl 안 부름
    assert collected == [1]
    assert set(out["results"]) == {"collect", "bot"}
    assert out["results"]["collect"] == {"ok": True, "detail": "수집 다시 실행 후 정상"}
    assert out["messages_sent"] is False
