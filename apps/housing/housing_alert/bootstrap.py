"""초기화: DB 생성, 예시 필터 등록. (unifi 에서는 앱이 처음 뜰 때 한 번 부른다)"""
from __future__ import annotations

import json
import sqlite3

from . import db
from .config import Config
from .cooperative import DEFAULT_KEYWORDS
from .filters import DEFAULT_FILTERS, normalize_config


def insert_default_filters(conn: sqlite3.Connection) -> int:
    if conn.execute("SELECT COUNT(*) FROM filters").fetchone()[0]:
        return 0
    now = db.now_iso()
    for name, raw in DEFAULT_FILTERS:
        conn.execute(
            "INSERT INTO filters(name, enabled, config, created_at, updated_at) VALUES(?,?,?,?,?)",
            (name, 0, json.dumps(normalize_config(raw), ensure_ascii=False), now, now),
        )
    return len(DEFAULT_FILTERS)


def init_db(conn: sqlite3.Connection, cfg: Config) -> dict:
    out = {"filters_added": insert_default_filters(conn)}
    if db.get_setting(conn, "coop_keywords") is None:
        db.set_setting(conn, "coop_keywords", list(DEFAULT_KEYWORDS))
    return out
