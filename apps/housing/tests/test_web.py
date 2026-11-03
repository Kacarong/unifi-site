import re

import pytest
from fastapi.testclient import TestClient

from housing_alert import db
from housing_alert.bootstrap import insert_default_filters
from housing_alert.web.app import create_app


@pytest.fixture
def client(cfg, conn):
    insert_default_filters(conn)
    conn.execute("""INSERT INTO notices(source, source_id, org, title, supply_type, notice_kind, sido, first_seen_at, updated_at,
                    cooperative_suspect, cooperative_reason, apply_end)
                    VALUES('lh','1','LH','○○ 행복주택 입주자 모집','행복주택','모집','서울','2026-10-07','2026-10-07',0,NULL,'2099-01-01'),
                          ('sh','2','SH','○○ 협동조합 조합원 모집','일반 민간임대','모집','서울','2026-10-07','2026-10-07',1,
                           '{"text": "제목 키워드 ''협동조합''", "matches": [{"keyword": "협동조합", "where": "title", "snippet": "○○ 협동조합 조합원"}]}','2099-01-01')""")
    return TestClient(create_app(cfg))


def csrf(client, path="/"):
    html = client.get(path).text
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


def test_no_login_required(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200 and "로그아웃" not in r.text and "비밀번호" not in client.get("/settings").text
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/login").status_code == 404


def test_pages_render(client):
    for path in ["/", "/notices", "/notices?show=coop", "/notices/2", "/filters", "/filters/new", "/filters/1", "/settings"]:
        r = client.get(path)
        assert r.status_code == 200, path
    import html as _html
    assert "제외됨(사유: 제목 키워드 '협동조합')" in _html.unescape(client.get("/notices?show=coop").text)
    assert "미발송" in client.get("/").text


def test_filter_toggle_and_preview(client, conn):
    token = csrf(client, "/filters")
    r = client.post("/filters/5/toggle", data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    row = conn.execute("SELECT enabled, enabled_at FROM filters WHERE id=5").fetchone()
    assert row["enabled"] == 1 and row["enabled_at"]
    data = client.get("/api/filters/5/preview").json()
    assert data["count"] == 1 and data["coop_blocked"] == 1
    r = client.post("/api/filters/preview", data={"csrf": token, "sidos": ["부산"], "exclude_closed": "on"})
    assert r.json()["count"] == 0


def test_csrf_required(client):
    r = client.post("/filters/1/toggle", data={"csrf": "bad"})
    assert r.status_code == 400


def test_cross_site_post_rejected_even_with_valid_token(client, conn):
    # 로그인이 없어 토큰은 누구나 얻을 수 있으므로 출처(Origin/Referer/Sec-Fetch-Site)로 막는다
    token = csrf(client, "/filters")
    for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"},
                    {"Referer": "https://evil.example/page"}, {"Sec-Fetch-Site": "cross-site"}):
        r = client.post("/filters/5/toggle", data={"csrf": token}, headers=headers, follow_redirects=False)
        assert r.status_code == 400, headers
    assert conn.execute("SELECT enabled FROM filters WHERE id=5").fetchone()[0] == 0
    r = client.post("/filters/5/toggle", data={"csrf": token}, follow_redirects=False,
                    headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 303
    assert conn.execute("SELECT enabled FROM filters WHERE id=5").fetchone()[0] == 1


def test_save_filter_from_form(client, conn):
    token = csrf(client, "/filters/new")
    r = client.post("/filters/save", data={
        "csrf": token, "name": "테스트", "sidos": ["서울", "경기"], "supply_types": ["행복주택"],
        "deposit_max": "5000", "exclude_closed": "on", "unknown_policy": "exclude",
    }, follow_redirects=False)
    assert r.status_code == 303
    import json
    row = conn.execute("SELECT * FROM filters WHERE name='테스트'").fetchone()
    c = json.loads(row["config"])
    assert c["sidos"] == ["서울", "경기"] and c["deposit_max"] == 50_000_000
    assert c["exclude_closed"] is True and c["recruit_only"] is False and c["unknown_policy"] == "exclude"
    assert row["enabled"] == 0


def test_settings_webhook_is_masked(client, conn):
    token = csrf(client, "/settings")
    hook = "https://discord.com/api/webhooks/123456789012/SECRETTOKENVALUE_abcd"
    r = client.post("/settings/webhook", data={"csrf": token, "webhook_url": hook, "action": "save"}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/settings").text
    assert "SECRETTOKENVALUE" not in page and "abcd" in page
    assert db.get_setting(conn, "webhook_url") == hook
    r = client.post("/settings/webhook", data={"csrf": token, "webhook_url": "https://evil.example/x", "action": "save"}, follow_redirects=False)
    assert "err=" in r.headers["location"]


def test_coop_override(client, conn):
    token = csrf(client, "/notices/2")
    client.post("/notices/2/coop-override", data={"csrf": token, "value": "1"})
    assert conn.execute("SELECT coop_override FROM notices WHERE id=2").fetchone()[0] == 1


def test_base_path(cfg, conn):
    cfg.base_path = "/housing"
    c = TestClient(create_app(cfg))
    assert c.get("/housing/api/health").json() == {"ok": True}
    assert c.get("/", follow_redirects=False).headers["location"] == "/housing/"
    assert c.get("/housing/", follow_redirects=False).status_code == 200
    assert 'href="/housing/static/style.css"' in c.get("/housing/").text
    assert c.get("/housing/static/style.css").status_code == 200


def test_bot_dm_settings(client, conn):
    token = csrf(client, "/settings")
    bot_token = "B" * 30 + "SECRETPART" + "Z" * 30
    r = client.post("/settings/bot", data={"csrf": token, "action": "save", "bot_token": bot_token,
                                           "dm_user_id": "abc"}, follow_redirects=False)
    assert "err=" in r.headers["location"] and db.get_setting(conn, "bot_token") is None
    r = client.post("/settings/bot", data={"csrf": token, "action": "save", "bot_token": bot_token,
                                           "dm_user_id": "342251718551273473"}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    assert db.get_setting(conn, "bot_token") == bot_token
    html = client.get("/settings").text
    assert "SECRETPART" not in html and "342251718551273473" in html
    # 토큰을 비우고 저장하면 기존 토큰 유지
    client.post("/settings/bot", data={"csrf": token, "action": "save", "bot_token": "",
                                       "dm_user_id": "342251718551273474"}, follow_redirects=False)
    assert db.get_setting(conn, "bot_token") == bot_token and db.get_setting(conn, "dm_user_id") == "342251718551273474"
    assert client.get("/api/status").json()["bot_dm_configured"] is True
    client.post("/settings/bot", data={"csrf": token, "action": "clear"}, follow_redirects=False)
    assert db.get_setting(conn, "bot_token") is None and db.get_setting(conn, "webhook_set_at") is None


def test_daily_report_setting(client, conn):
    token = csrf(client, "/settings")
    assert "정상 작동 점검" in client.get("/settings").text
    client.post("/settings/report", data={"csrf": token, "hour": "21"}, follow_redirects=False)
    assert db.get_setting(conn, "daily_report") == {"enabled": False, "hour": 21}
    client.post("/settings/report", data={"csrf": token, "enabled": "1", "hour": "8"}, follow_redirects=False)
    assert db.get_setting(conn, "daily_report") == {"enabled": True, "hour": 8}
