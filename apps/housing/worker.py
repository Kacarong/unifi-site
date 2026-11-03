"""수집·점검을 unifi 서버 안에서 돌린다 (예전 systemd 타이머 두 개를 대신한다).

- 수집: 30분마다 깨어나 run_collection 을 부른다. 실제로 받을지는 웹 설정의 수집 간격(주간 60분,
  야간 180분)과 출처별 실패 백오프를 보고 pipeline 이 정한다.
- 점검: 15분마다. 수집이 멈췄으면 그 자리에서 한 번 수집하고, 봇 토큰이 무효인지 본다.
"""
from __future__ import annotations

import logging
import threading
import time

from .housing_alert import db, healthcheck, pipeline
from .housing_alert.config import Config

log = logging.getLogger("housing")

COLLECT_EVERY = 30 * 60
HEALTH_EVERY = 15 * 60
FIRST_DELAY = 60  # 서버가 뜨자마자 몰리지 않게


class Worker:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="housing-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _collect(self) -> None:
        pipeline.collect_in_background(self.cfg, force=False, trigger="timer")

    def _health(self) -> None:
        conn = db.connect(self.cfg.db_path)
        try:
            healthcheck.run_healthcheck(
                conn, self.cfg,
                collect_now=lambda: pipeline.collect_in_background(self.cfg, force=True, trigger="healthcheck"),
            )
        finally:
            conn.close()

    def _loop(self) -> None:
        jobs = [(self._collect, COLLECT_EVERY), (self._health, HEALTH_EVERY)]
        due = [time.monotonic() + FIRST_DELAY] * len(jobs)
        while not self._stop.wait(5):
            for i, (job, every) in enumerate(jobs):
                if time.monotonic() < due[i]:
                    continue
                try:
                    job()
                except Exception:  # noqa: BLE001 - 루프는 죽지 않는다
                    log.exception("housing %s 예외", job.__name__)
                due[i] = time.monotonic() + every
