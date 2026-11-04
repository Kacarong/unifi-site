"""백그라운드 일꾼 — 원본 갱신 확인, 알림 보내기.

한 시간마다 한 번 깬다.
  - 원본(공공데이터포털)은 6시간마다 파일 번호만 확인하고 바뀌었을 때만 받는다.
  - 한국장학재단 실시간 포털, 드림스폰, 공고 게시판(대한토목학회·재단)은 6시간마다 본다.
    CSV 는 한 달에 한 번이라, 그 사이에 올라온 공고를 여기서 채운다.
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

from . import boards, dreamspon, kosaf, logic, source, store

log = logging.getLogger("unifi.scholarship")

KST = ZoneInfo("Asia/Seoul")
TICK_SECONDS = 3600
SYNC_EVERY_SECONDS = 6 * 3600
EXTRA_EVERY_SECONDS = 6 * 3600
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


KEEP_DAYS = 180  # 모아 둔 공고는 마감이 이만큼 지날 때까지 남긴다('최근 마감' 탭과 같은 기간)


def _still_relevant(it: dict[str, Any], today: dt.date) -> bool:
    end = logic.parse_date(it.get("end", ""))
    if end:
        return (today - end).days <= KEEP_DAYS
    posted = logic.parse_date(it.get("posted", ""))
    return bool(posted) and (today - posted).days <= boards.RECENT_DAYS


def keep_previous(prev: list[dict[str, Any]], fresh: list[dict[str, Any]], today: dt.date,
                  allowed=lambda it: True) -> list[dict[str, Any]]:
    """이번에 다시 못 본 공고도 지우지 않는다. 게시판 첫 쪽에서 밀려났거나, 사이트가 잠깐
    안 열렸거나, 포털 최근 쪽에서 내려갔을 뿐이다. 이번에 다시 본 것(같은 id)은 새 내용으로."""
    ids = {it["id"] for it in fresh}
    return fresh + [it for it in prev if it["id"] not in ids and allowed(it) and _still_relevant(it, today)]


def sync_extra(today: dt.date | None = None) -> dict[str, Any]:
    """CSV 에 아직 없는 장학금을 포털·드림스폰·게시판에서 모은다. 한쪽이 실패해도 다른 쪽은 남긴다."""
    today = today or now_kst().date()
    base = store.base_items()
    known = {(it["org"], it["name"], it.get("end", "")) for it in base}
    errors: list[str] = []
    prev = store.extra_items()
    prev_dream = [it for it in prev if it.get("aggregator")]
    prev_portal = [it for it in prev if not it.get("notice_title") and not it.get("aggregator")]
    prev_notices = [it for it in prev if it.get("notice_title")]

    cache = store.kosaf_cache()
    portal: list[dict[str, Any]] = []
    try:
        portal = kosaf.collect(known, cache, today)
        # 캐시는 최근 것만 남긴다 — 마감이 오래 지난 것은 다시 볼 일이 없다
        cutoff = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
        store.save_kosaf_cache({k: v for k, v in cache.items() if (v.get("end") or "9") >= cutoff})
    except source.SourceError as exc:
        errors.append(str(exc))
    portal = keep_previous(prev_portal, portal, today)

    dream: list[dict[str, Any]] = []
    try:
        dream = dreamspon.collect(today, log=log)
    except dreamspon.DreamsponError as exc:
        errors.append(str(exc))
    dream = keep_previous(prev_dream, dream, today)

    state = store.snapshot()
    active = boards.active_sources(state)
    active_ids = {b["id"] for b in active}
    label_to_id = {b["label"]: b["id"] for b in boards.all_sources(state)}

    def from_active(it: dict[str, Any]) -> bool:
        # 끄거나 지운 게시판의 공고는 남기지 않는다(예전 자료는 source_id 가 없어 이름으로 찾는다)
        return (it.get("source_id") or label_to_id.get(it.get("source", ""))) in active_ids

    notices: list[dict[str, Any]] = []
    try:
        stats: dict[str, dict[str, Any]] = {}
        notices = boards.collect(active, today=today, log=log, stats=stats)
        store.update({"source_stats": {k: {**v, "at": time.time()} for k, v in stats.items()}})
    except Exception as exc:  # noqa: BLE001 - 게시판 쪽 예외로 포털 결과까지 잃지 않는다
        errors.append(f"공고 게시판: {exc}")
    notices = keep_previous(prev_notices, notices, today, from_active)

    store.replace_extras(portal + dream + notices)
    store.update({"last_extra_at": time.time(), "extra_error": " / ".join(errors)})
    log.info("추가 출처: 포털 %d건, 드림스폰 %d건, 게시판 %d건", len(portal), len(dream), len(notices))
    return {"portal": len(portal), "dreamspon": len(dream), "boards": len(notices), "errors": errors}


# ---------------- 디스코드 ----------------
def _mention(m: str) -> str:
    m = (m or "").strip()
    if m.lstrip("@").isdigit():
        return f"<@{m.lstrip('@')}>"
    return m


DISCORD_API = "https://discord.com/api/v10"


def discord_target(settings: dict[str, Any]) -> tuple[str, str] | None:
    """(봇 토큰, 채널 ID). 둘 중 하나라도 없으면 알림을 보낼 곳이 없다."""
    token = (settings.get("discord_bot_token") or "").strip()
    channel = (settings.get("discord_channel_id") or "").strip()
    return (token, channel) if token and channel else None


def _discord_reason(exc: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(exc.read().decode("utf-8", "replace")).get("message", "")
    except Exception:  # noqa: BLE001
        detail = ""
    hint = {
        401: "봇 토큰이 틀렸거나 재발급돼 무효가 됐습니다. 개발자 포털에서 토큰을 다시 복사해 주세요",
        403: "봇이 그 채널에 글을 쓸 권한이 없습니다. 봇을 서버에 초대하고 채널 보기·메시지 보내기·링크 첨부 권한을 주세요",
        404: "채널을 찾지 못했습니다. 채널 ID가 맞는지, 봇이 그 서버에 들어가 있는지 확인해 주세요",
    }.get(exc.code, "")
    head = f"디스코드가 거절했습니다 (HTTP {exc.code}{', ' + detail if detail else ''})"
    return f"{head}. {hint}" if hint else head


def post_discord(target: tuple[str, str], payload: dict[str, Any]) -> None:
    """봇 토큰으로 채널에 메시지를 올린다."""
    token, channel = target
    req = urllib.request.Request(
        f"{DISCORD_API}/channels/{channel}/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            # 디스코드는 봇 요청에 이 형식의 User-Agent 를 요구한다
            "User-Agent": "DiscordBot (https://unifi.kacarong.kr, 1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_discord_reason(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"디스코드에 보내지 못했습니다: {exc}") from exc


def _line(it: dict[str, Any], today: dt.date) -> str:
    left = logic.dday(it, today)
    when = f"~{it['end'][5:].replace('-', '/')} 마감" if it.get("end") else "마감일 미정"
    if left is not None and left >= 0:
        when += f" (D-{left})" if left else " (오늘 마감)"
    if logic.status(it, today) == "upcoming":
        when = f"{it['start'][5:].replace('-', '/')} 모집 시작"
    elif logic.status(it, today) == "unknown":
        when = "일정 미확인 · 공고 원문 확인"
    elif logic.status(it, today) == "year_round":
        when = f"연중 사업(~{it['end'][:10].replace('-', '/')}) · 지금 신청받는지는 공고 확인"
    if it.get("source"):
        when += f" · 출처 {it['source']}"
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
    embed["footer"] = {"text": "출처: 한국장학재단 학자금지원정보·포털, 드림스폰, 대한토목학회·재단 공고 · 자격은 공고 원문으로 꼭 확인하세요"}

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
    target = discord_target(settings)
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
        if target:
            try:
                send(target, build_message(note, settings, state.get("site_url", ""), today))
            except RuntimeError as exc:
                store.update({"notify_error": str(exc)})
                log.warning("%s", exc)
                break  # 다음 시간에 다시 — 보낸 표시를 안 했으니 놓치지 않는다
        # 봇이 없어도 표시는 한다. 나중에 봇을 넣는 순간 밀린 알림이 쏟아지면 안 된다.
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
                if time.time() - store.snapshot().get("last_extra_at", 0) >= EXTRA_EVERY_SECONDS:
                    sync_extra()
            except Exception:  # noqa: BLE001
                log.exception("추가 출처 동기화 예외")
            try:
                check()
            except Exception:  # noqa: BLE001
                log.exception("장학금 알림 예외")
            self._stop.wait(TICK_SECONDS)


worker = Worker()
