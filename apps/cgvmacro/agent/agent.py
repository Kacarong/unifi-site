"""로컬 PC 에이전트 — 통합 사이트에서 선점 작업을 받아 크롬으로 좌석을 잡는다.

통합 사이트(서버)는 CGV API 폴링/알림만 하고, 로그인된 크롬이 필요한 좌석
선점은 이 스크립트가 맡는다. 윈도우 PC에서 켜두기만 하면 된다.

    python agent.py --server http://192.168.10.9:8000

처음 한 번은 원본 cgv-macro GUI 로 예매 흐름을 '녹화'해서 recipe.json 을
만들어 두어야 한다(%APPDATA%\\CGV-Ticket-Watcher\\recipe.json).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cgv_macro import cgv_api, paths  # noqa: E402

PERSON_KEYS = {"general": "일반", "teen": "청소년", "senior": "우대"}


class ServerClient:
    def __init__(self, base: str, token: str = "", agent_id: str = "") -> None:
        self.base = base.rstrip("/") + "/api/cgvmacro"
        self.token = token
        self.agent_id = agent_id or socket.gethostname()

    def _request(self, path: str, payload: dict | None = None) -> dict:
        url = self.base + path
        data = json.dumps(payload).encode() if payload is not None else b"{}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Agent-Token"] = self.token
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.load(res)

    def claim(self) -> dict | None:
        query = urllib.parse.urlencode({"agent_id": self.agent_id})
        return self._request(f"/agent/claim?{query}").get("job")

    def progress(self, job_id: str, message: str, status: str | None = None) -> None:
        body: dict = {"message": message}
        if status:
            body["status"] = status
        self._request(f"/agent/jobs/{job_id}/progress", body)

    def finish(self, job_id: str, ok: bool, result: dict | None = None, error: str = "") -> None:
        self._request(
            f"/agent/jobs/{job_id}/result",
            {"status": "done" if ok else "error", "result": result, "error": error},
        )


def load_recipe() -> dict:
    recipe_path = os.path.join(paths.data_dir(), "recipe.json")
    if not os.path.exists(recipe_path):
        raise SystemExit(
            f"녹화 파일이 없습니다: {recipe_path}\n"
            "원본 cgv-macro GUI 에서 예매 흐름을 한 번 녹화해 주세요."
        )
    with open(recipe_path, encoding="utf-8") as fh:
        return json.load(fh)


def pick_showtime(job: dict) -> tuple[str, str]:
    """작업에 회차가 지정돼 있으면 그대로, 없으면 지금 예매 가능한 첫 회차를 고른다."""
    showtime = job.get("showtime") or {}
    if showtime.get("time"):
        return showtime["time"], showtime.get("screen", "")

    mov_no, _mov_nm = cgv_api.resolve_movie(job.get("movie", ""), job.get("movie_code", ""))
    site_no, _site_nm, _region = cgv_api.resolve_theater(
        job.get("theater", ""), job.get("theater_code", "")
    )
    found = cgv_api.fetch_showtimes(mov_no, site_no, job.get("date", "").replace("-", ""))
    for s in found:
        if not s.soldout and not s.controlled and s.remaining > 0:
            return s.time, s.screen
    raise RuntimeError("지금 잡을 수 있는 회차가 없습니다.")


def run_job(client: ServerClient, job: dict, recipe: dict) -> None:
    from cgv_macro.replayer import Grabber  # playwright 는 실제 선점 때만 필요

    job_id = job["id"]
    grab = job.get("grab") or {}
    persons = {ko: int(grab.get(en, 0)) for en, ko in PERSON_KEYS.items() if int(grab.get(en, 0)) > 0}
    preferred = [s.strip().upper() for s in str(grab.get("seats", "")).split(",") if s.strip()]

    client.progress(job_id, "작업 수신 — 크롬 준비 중", status="running")

    with Grabber(headless=False) as grabber:
        if not grabber.ensure_login(timeout_s=600):
            client.finish(job_id, False, error="CGV 로그인이 확인되지 않았습니다.")
            return

        hhmm, screen = pick_showtime(job)
        client.progress(job_id, f"{job.get('date')} {hhmm} {screen} 회차로 선점 시도")

        ok, seat, message = grabber.replay(
            recipe,
            day=job.get("date", ""),
            hhmm=hhmm,
            movie=job.get("movie", ""),
            persons=persons or {"일반": 2},
            preferred=preferred,
            only_preferred=bool(grab.get("seats_only")),
            log=lambda m: client.progress(job_id, m),
        )

    if ok:
        client.finish(job_id, True, result={"seat": seat, "showtime": hhmm, "message": message})
        print(f"[선점 완료] {seat} — 결제만 하면 됩니다.")
    else:
        client.finish(job_id, False, error=message or "좌석 선점 실패")
        print(f"[선점 실패] {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="unifi-site CGV 선점 에이전트")
    parser.add_argument("--server", required=True, help="통합 사이트 주소 (예: http://192.168.10.9:8000)")
    parser.add_argument("--token", default=os.environ.get("UNIFI_AGENT_TOKEN", ""), help="에이전트 토큰")
    parser.add_argument("--agent-id", default="", help="에이전트 식별자 (기본: 호스트명)")
    parser.add_argument("--interval", type=float, default=3.0, help="작업 확인 주기(초)")
    args = parser.parse_args()

    client = ServerClient(args.server, args.token, args.agent_id)
    recipe = load_recipe()
    print(f"에이전트 '{client.agent_id}' 시작 — {client.base}")

    while True:
        try:
            job = client.claim()
            if job:
                print(f"작업 수신: {job['id']} ({job.get('target_name')})")
                try:
                    run_job(client, job, recipe)
                except Exception as exc:  # noqa: BLE001 - 실패해도 에이전트는 계속 돈다
                    print(f"작업 실패: {exc}")
                    client.finish(job["id"], False, error=str(exc))
                continue  # 다음 작업이 있을 수 있으니 바로 재확인
        except urllib.error.URLError as exc:
            print(f"서버 연결 실패: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"오류: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
