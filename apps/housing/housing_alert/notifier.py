"""디스코드 발송 (봇 DM 또는 웹훅).

- 봇 토큰과 받는 사람 사용자 ID가 설정돼 있으면 기본 발송은 봇 DM, 아니면 기본 웹훅을 쓴다.
  필터에 따로 지정한 웹훅은 그대로 그 웹훅으로 보낸다.
- 발송 대상이 없으면 알림은 notifications 테이블에 'pending'(미발송)으로 남는다.
- 발송 대상을 새로 넣은 시각(webhook_set_at) 이전에 쌓인 미발송분은 '밀린 알림'으로 보고,
  사용자가 웹에서 '모두 보내기' 또는 '모두 버리기'를 고를 때까지 자동 발송하지 않는다.
- 한 번에 보낼 공고가 summary_threshold(기본 10)건을 넘으면 요약 메시지로 묶는다.
- 429는 retry_after만큼 기다렸다 재시도한다.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections import OrderedDict
from typing import Any, Callable

import httpx

from . import db
from .config import Config

log = logging.getLogger(__name__)

DEFAULT_SUMMARY_THRESHOLD = 10
DEFAULT_TARGET = "__default__"  # 필터 전용 웹훅이 없을 때: 봇 DM 또는 기본 웹훅
DISCORD_API = "https://discord.com/api/v10"
USER_ID_RE = re.compile(r"^\d{17,20}$")
WEBHOOK_RE = re.compile(r"^https://(?:canary\.|ptb\.)?(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[\w-]+$")
SOURCE_COLORS = {"LH": 0x0B6E4F, "SH": 0x1F5FAE, "GH": 0xE07A1F, "청약홈": 0x7B3FA0}


class WebhookError(RuntimeError):
    pass


def valid_webhook(url: str) -> bool:
    return bool(WEBHOOK_RE.match((url or "").strip()))


def mask_secret(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= keep * 2:
        return "*" * len(value)
    return value[:keep] + "…" + "*" * 6 + value[-keep:]


def mask_webhook(url: str | None) -> str:
    if not url:
        return ""
    m = re.match(r"^(https://[^/]+/api/webhooks/)(\d+)/(.+)$", url)
    if not m:
        return mask_secret(url)
    return f"{m.group(1)}{m.group(2)[:4]}…/{'*' * 8}{m.group(3)[-4:]}"


def get_webhook(conn: sqlite3.Connection, cfg: Config) -> str:
    return db.get_setting(conn, "webhook_url") or cfg.discord_webhook_url or ""


def get_bot_dm(conn: sqlite3.Connection) -> "BotDM | None":
    token = db.get_setting(conn, "bot_token")
    user_id = db.get_setting(conn, "dm_user_id")
    return BotDM(token, user_id) if token and user_id else None


def get_sender(conn: sqlite3.Connection, cfg: Config) -> "Callable[..., None] | None":
    """기본 발송 함수 (client, payload, sleep=) -> None. 봇 DM이 우선, 없으면 웹훅, 둘 다 없으면 None."""
    dm = get_bot_dm(conn)
    if dm:
        return dm.send
    url = get_webhook(conn, cfg)
    return webhook_sender(url) if url else None


def webhook_sender(url: str) -> Callable[..., None]:
    def send(client: httpx.Client, payload: dict, sleep=time.sleep) -> None:
        send_webhook(client, url, payload, sleep=sleep)
    return send


# ------------------------------------------------------------------ 메시지 구성

def _won(v: int | None) -> str | None:
    if v is None:
        return None
    if v >= 100_000_000:
        eok, rest = divmod(v, 100_000_000)
        man = rest // 10_000
        return f"{eok}억" + (f" {man:,}만" if man else "") + "원"
    if v >= 10_000:
        return f"{v // 10_000:,}만원"
    return f"{v:,}원"


def _range(lo, hi, fmt: Callable[[Any], str]) -> str | None:
    if lo is None and hi is None:
        return None
    if lo is None or hi is None or lo == hi:
        return fmt(lo if lo is not None else hi)
    return f"{fmt(lo)} ~ {fmt(hi)}"


def notice_facts(n: dict) -> list[tuple[str, str]]:
    from .collectors import SOURCE_LABELS

    region = " ".join(filter(None, [(n.get("sido") or "").replace(",", "·"), n.get("sigungu")])) or n.get("region_raw")
    period = None
    if n.get("apply_start") or n.get("apply_end"):
        period = f"{n.get('apply_start') or '?'} ~ {n.get('apply_end') or '?'}"
    facts = [
        ("출처", SOURCE_LABELS.get(n.get("source"), n.get("source") or "")),
        ("유형", n.get("supply_type") or n.get("category_raw") or "기타"),
        ("지역", region),
        ("접수기간", period),
        ("공고일", n.get("posted_date")),
        ("공급 세대수", f"{n['households']:,}세대" if n.get("households") else None),
        ("전용면적", _range(n.get("area_min"), n.get("area_max"), lambda v: f"{v:g}㎡")),
        ("임대보증금", _range(n.get("deposit_min"), n.get("deposit_max"), _won)),
        ("월 임대료", _range(n.get("rent_min"), n.get("rent_max"), _won)),
        ("분양가", _range(n.get("price_min"), n.get("price_max"), _won)),
    ]
    return [(k, v) for k, v in facts if v]


def notice_title(n: dict, kind: str = "new") -> str:
    prefix = ""
    if kind == "remind":
        prefix = "[D-1 마감] "
    elif n.get("is_correction"):
        prefix = "[정정] "
    return (prefix + (n.get("title") or ""))[:256]


def build_notice_embed(n: dict, filter_names: list[str], kind: str = "new") -> dict:
    fields = [{"name": k, "value": str(v)[:1024], "inline": True} for k, v in notice_facts(n)]
    fields.append({"name": "매칭 필터", "value": ", ".join(filter_names)[:1024] or "-", "inline": False})
    embed = {
        "title": notice_title(n, kind),
        "color": SOURCE_COLORS.get(n.get("org") or "", 0x555555),
        "fields": fields[:25],
        "footer": {"text": "housing-alert"},
    }
    if n.get("url") and str(n["url"]).startswith("http"):
        embed["url"] = n["url"]
    return embed


def build_summary_embeds(items: list[tuple[dict, list[str], str]]) -> list[dict]:
    """items: (notice, filter_names, kind). 설명란 4096자 제한에 맞춰 여러 embed로 나눈다."""
    lines = []
    for n, names, kind in items:
        title = notice_title(n, kind).replace("[", "(").replace("]", ")")
        link = f"[{title[:120]}]({n['url']})" if n.get("url") else title[:120]
        meta = " · ".join(filter(None, [
            n.get("org"), n.get("supply_type"), (n.get("sido") or "").replace(",", "·"),
            f"~{n['apply_end']}" if n.get("apply_end") else None,
        ]))
        lines.append(f"• {link}\n  {meta} | 필터: {', '.join(names)}")
    embeds: list[dict] = []
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 3900:
            embeds.append(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        embeds.append(chunk)
    total = len(items)
    return [
        {"title": f"새 공고 {total}건 요약" + (f" ({i + 1}/{len(embeds)})" if len(embeds) > 1 else ""),
         "description": desc, "color": 0x444444, "footer": {"text": "housing-alert"}}
        for i, desc in enumerate(embeds)
    ]


# ------------------------------------------------------------------ 전송

def _post(client: httpx.Client, url: str, payload: dict, *, params: dict | None = None,
          headers: dict | None = None, max_attempts: int = 5, sleep=time.sleep) -> httpx.Response:
    """429는 retry_after만큼, 5xx·네트워크 오류는 지수 대기 후 재시도한다."""
    for attempt in range(max_attempts):
        try:
            resp = client.post(url, params=params, headers=headers, json=payload, timeout=20)
        except httpx.HTTPError as exc:
            if attempt == max_attempts - 1:
                raise WebhookError(f"전송 실패: {type(exc).__name__}") from None
            sleep(2 ** attempt)
            continue
        if resp.status_code == 429:
            retry_after = 1.0
            try:
                retry_after = float(resp.json().get("retry_after", 1.0))
            except (ValueError, AttributeError):
                retry_after = float(resp.headers.get("Retry-After", "1") or 1)
            sleep(min(max(retry_after, 0.5), 60))
            continue
        if resp.status_code >= 500:
            sleep(2 ** attempt)
            continue
        if resp.status_code >= 400:
            code = ""
            try:
                code = f" (code {int(resp.json().get('code'))})"
            except (ValueError, AttributeError, TypeError):
                pass
            raise WebhookError(f"디스코드 응답 HTTP {resp.status_code}{code}")
        # 남은 요청 수가 0이면 버킷 리셋까지 쉰다
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            try:
                sleep(min(float(resp.headers.get("X-RateLimit-Reset-After", "1")), 60))
            except ValueError:
                pass
        return resp
    raise WebhookError("재시도 한도 초과(429/5xx)")


def send_webhook(client: httpx.Client, url: str, payload: dict, max_attempts: int = 5, sleep=time.sleep) -> None:
    payload = {"username": "공고 알림", "allowed_mentions": {"parse": []}, **payload}
    _post(client, url, payload, params={"wait": "true"}, max_attempts=max_attempts, sleep=sleep)


class BotDM:
    """봇 토큰으로 사용자에게 DM을 보낸다. DM 채널 ID는 인스턴스 안에서 한 번만 연다."""

    def __init__(self, token: str, user_id: str) -> None:
        self.headers = {"Authorization": f"Bot {token}", "User-Agent": "DiscordBot (housing-alert, 1.0)"}
        self.user_id = str(user_id)
        self.channel_id: str | None = None

    def send(self, client: httpx.Client, payload: dict, sleep=time.sleep) -> None:
        if self.channel_id is None:
            resp = _post(client, f"{DISCORD_API}/users/@me/channels", {"recipient_id": self.user_id},
                         headers=self.headers, sleep=sleep)
            try:
                self.channel_id = str(resp.json()["id"])
            except (ValueError, KeyError, TypeError):
                raise WebhookError("DM 채널을 열지 못했습니다") from None
        _post(client, f"{DISCORD_API}/channels/{self.channel_id}/messages",
              {"allowed_mentions": {"parse": []}, **payload}, headers=self.headers, sleep=sleep)


def send_text(client: httpx.Client, sender: Callable[..., None], content: str, sleep=time.sleep) -> None:
    sender(client, {"content": content[:1900]}, sleep=sleep)


def dispatch_pending(
    conn: sqlite3.Connection,
    cfg: Config,
    client: httpx.Client | None = None,
    include_backlog: bool = False,
    sleep=time.sleep,
) -> dict[str, int]:
    """미발송 알림을 보낸다. 반환: {'sent': n, 'failed': n, 'waiting': n}"""
    default_sender = get_sender(conn, cfg)
    webhook_set_at = db.get_setting(conn, "webhook_set_at")
    threshold = int(db.get_setting(conn, "summary_threshold", DEFAULT_SUMMARY_THRESHOLD) or DEFAULT_SUMMARY_THRESHOLD)
    rows = conn.execute(
        """
        SELECT nt.id AS nid, nt.kind, nt.created_at AS queued_at, f.id AS fid, f.name AS filter_name,
               f.webhook_url AS filter_webhook, n.*
        FROM notifications nt
        JOIN notices n ON n.id = nt.notice_id
        JOIN filters f ON f.id = nt.filter_id
        WHERE nt.status = 'pending'
        ORDER BY n.posted_date, n.id
        """
    ).fetchall()
    groups: dict[str, OrderedDict] = {}
    waiting = 0
    for r in rows:
        r = dict(r)
        target = r["filter_webhook"] or (DEFAULT_TARGET if default_sender else None)
        if not target:
            waiting += 1
            continue
        if not include_backlog and r["filter_webhook"] is None and webhook_set_at and r["queued_at"] < webhook_set_at:
            waiting += 1  # 밀린 알림: 사용자 선택 대기
            continue
        bucket = groups.setdefault(target, OrderedDict())
        key = (r["id"], r["kind"])
        entry = bucket.setdefault(key, {"notice": r, "names": [], "nids": [], "kind": r["kind"]})
        entry["names"].append(r["filter_name"])
        entry["nids"].append(r["nid"])

    stats = {"sent": 0, "failed": 0, "waiting": waiting}
    if not groups:
        return stats
    own_client = client is None
    client = client or httpx.Client()
    try:
        for target, bucket in groups.items():
            send = default_sender if target == DEFAULT_TARGET else webhook_sender(target)
            entries = list(bucket.values())
            try:
                if len(entries) > threshold:
                    embeds = build_summary_embeds([(e["notice"], e["names"], e["kind"]) for e in entries])
                    for emb in embeds:
                        send(client, {"embeds": [emb]}, sleep=sleep)
                    _mark(conn, [nid for e in entries for nid in e["nids"]], "sent")
                    stats["sent"] += sum(len(e["nids"]) for e in entries)
                else:
                    for e in entries:
                        try:
                            send(client, {"embeds": [build_notice_embed(e["notice"], e["names"], e["kind"])]}, sleep=sleep)
                            _mark(conn, e["nids"], "sent")
                            stats["sent"] += len(e["nids"])
                        except WebhookError as exc:
                            _mark(conn, e["nids"], "pending", str(exc))
                            stats["failed"] += len(e["nids"])
                            log.warning("알림 전송 실패: %s", exc)
            except WebhookError as exc:
                stats["failed"] += sum(len(e["nids"]) for e in entries)
                for e in entries:
                    _mark(conn, e["nids"], "pending", str(exc))
                log.warning("요약 전송 실패: %s", exc)
    finally:
        if own_client:
            client.close()
    return stats


def _mark(conn: sqlite3.Connection, ids: list[int], status: str, error: str | None = None) -> None:
    if not ids:
        return
    sent_at = db.now_iso() if status == "sent" else None
    conn.executemany(
        "UPDATE notifications SET status=?, sent_at=COALESCE(?, sent_at), error=? WHERE id=?",
        [(status, sent_at, error, i) for i in ids],
    )


def backlog_count(conn: sqlite3.Connection) -> int:
    webhook_set_at = db.get_setting(conn, "webhook_set_at")
    if not webhook_set_at:
        return conn.execute("SELECT COUNT(*) FROM notifications WHERE status='pending'").fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE status='pending' AND created_at < ?", (webhook_set_at,)
    ).fetchone()[0]


def discard_backlog(conn: sqlite3.Connection) -> int:
    webhook_set_at = db.get_setting(conn, "webhook_set_at") or "9999"
    cur = conn.execute(
        "UPDATE notifications SET status='discarded' WHERE status='pending' AND created_at < ?", (webhook_set_at,)
    )
    return cur.rowcount
