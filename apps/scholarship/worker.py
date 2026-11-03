"""백그라운드 일꾼 — 원본 갱신 확인, 알림 보내기.

한 시간마다 한 번 깬다.
  - 원본(공공데이터포털)은 6시간마다 파일 번호만 확인하고 바뀌었을 때만 받는다.
  - 알림은 깨어날 때마다 고르되, 밤(22시~8시)에는 보내지 않고 아침까지 미룬다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo

from . import logic, source, store

log = logging.getLogger("unifi.scholarship")

KST = ZoneInfo("Asia/Seoul")
TICK_SECONDS = 3600
SYNC_EVERY_SECONDS = 6 * 3600
QUIET_HOURS = (22, 8)  # 22시부터 다음날 8시 전까지는 보내지 않는다


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


# ---------------- 원본 동기화 ----------------
def sync(force: bool = False) -> dict[str, Any]:
    """파일 번호가 바뀌었을 때만 CSV 를 다시 받는다. force 면 무조건 받는다."""
    state = store.snapshot()
    try:
        meta = source.fetch_meta()
        changed = force or meta.get("file_id") != state["meta"].get("file_id") or not store.items()
        if changed:
            items = source.parse(source.fetch_csv(meta))
            store.replace_items(items)
            log.info("장학금 %d건 받음 (%s)", len(items), meta.get("name"))
        store.update({"meta": meta, "last_sync_at": time.time(), "last_error": ""})
        return {"changed": changed, "count": len(store.items()), "meta": meta}
    except source.SourceError as exc:
        store.update({"last_error": str(exc), "last_sync_at": time.time()})
        raise


# ---------------- 디스코드 ----------------
def _mention(m: str) -> str:
    m = (m or "").strip()
    if m.lstrip("@").isdigit():
        return f"<@{m.lstrip('@')}>"
    return m


def post_discord(url: str, payload: dict[str, Any]) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "unifi-scholarship/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"디스코드가 거절했습니다 (HTTP {exc.code}). 웹훅 주소를 확인해 주세요") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"디스코드에 보내지 못했습니다: {exc}") from exc


def _line(it: dict[str, Any], today: dt.date) -> str:
    left = logic.dday(it, today)
    when = f"~{it['end'][5:].replace('-', '/')} 마감" if it.get("end") else "마감일 미정"
    if left is not None and left >= 0:
        when += f" (D-{left})" if left else " (오늘 마감)"
    if logic.status(it, today) == "upcoming":
        when = f"{it['start'][5:].replace('-', '/')} 모집 시작"
    support = (it.get("support") or "").replace("○", "").strip().splitlines()
    head = f"**{it['org']} · {it['name']}**"
    if it.get("url"):
        head = f"[{it['org']} · {it['name']}]({it['url']})"
    return f"• {head}\n  {when}" + (f" — {support[0][:60]}" if support else "")


def build_message(note: dict[str, Any], settings: dict[str, Any], site_url: str, today: dt.date) -> dict[str, Any]:
    items = note["items"]
    if note["kind"] == "new":
        title, color = f"🎓 내 조건에 맞는 새 장학금 {len(items)}건", 0x3B82F6
    elif note["kind"] == "star_new":
        title, color = "⭐ 관심 장학금 모집이 올라왔어요", 0xF59E0B
    else:
        left = note.get("dday", 0)
        title = "⏰ 관심 장학금 오늘 마감" if left == 0 else f"⏰ 관심 장학금 마감 D-{left}"
        color = 0xEF4444

    shown = items[:10]
    desc = "\n".join(_line(it, today) for it in shown)
    if len(items) > len(shown):
        desc += f"\n…외 {len(items) - len(shown)}건"
    embed: dict[str, Any] = {"title": title, "description": desc[:4000], "color": color}
    if site_url:
        embed["url"] = site_url.rstrip("/") + "/apps/scholarship/"
    embed["footer"] = {"text": "출처: 한국장학재단 학자금지원정보 · 자격은 공고 원문으로 꼭 확인하세요"}

    payload: dict[str, Any] = {"embeds": [embed]}
    mention = _mention(settings.get("discord_mention", ""))
    if mention:
        payload["content"] = mention
        payload["allowed_mentions"] = {"parse": ["users", "everyone"]}
    return payload


# ---------------- 알림 ----------------
def quiet(now: dt.datetime) -> bool:
    start, end = QUIET_HOURS
    return now.hour >= start or now.hour < end


def check(now: dt.datetime | None = None, send=post_discord) -> list[str]:
    """알림을 골라 보낸다. 보낸(또는 보낼 곳이 없어 넘긴) 알림 종류를 돌려준다."""
    now = now or now_kst()
    today = now.date()
    items = store.items()
    if not items:
        return []
    state = store.snapshot()
    current_ids = [it["id"] for it in items]

    # 처음에는 기준선만 잡는다. 이미 올라와 있던 장학금까지 '새 장학금'으로
    # 알리면 켜자마자 수십 건이 쏟아진다.
    if not state["baselined"]:
        store.update({"known_ids": current_ids, "baselined": True, "last_check_at": time.time()})
        return []
    if quiet(now):
        return []

    settings = state["settings"]
    url = (settings.get("discord_webhook_url") or "").strip()
    notes = logic.plan_notifications(
        items,
        profile=state["profile"],
        settings=settings,
        stars=state["stars"],
        known_ids=set(state["known_ids"]),
        sent=set(state["sent"]),
        today=today,
    )
    done: list[str] = []
    for note in notes:
        if url:
            try:
                send(url, build_message(note, settings, state.get("site_url", ""), today))
            except RuntimeError as exc:
                store.update({"notify_error": str(exc)})
                log.warning("%s", exc)
                break  # 다음 시간에 다시 — 보낸 표시를 안 했으니 놓치지 않는다
        # 웹훅이 없어도 표시는 한다. 나중에 웹훅을 넣는 순간 밀린 알림이 쏟아지면 안 된다.
        store.mark_sent(note["keys"])
        done.append(note["kind"])
    else:
        store.update({"known_ids": current_ids, "last_check_at": time.time(), "notify_error": ""})
    return done


# ---------------- 루프 ----------------
class Worker:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scholarship-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if time.time() - store.snapshot()["last_sync_at"] >= SYNC_EVERY_SECONDS:
                    sync()
            except source.SourceError as exc:
                log.warning("장학금 원본 갱신 실패: %s", exc)
            except Exception:  # noqa: BLE001 - 루프는 죽지 않는다
                log.exception("장학금 동기화 예외")
            try:
                check()
            except Exception:  # noqa: BLE001
                log.exception("장학금 알림 예외")
            self._stop.wait(TICK_SECONDS)


worker = Worker()
