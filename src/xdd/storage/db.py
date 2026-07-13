"""SQLite connection management and schema.

We use the stdlib ``sqlite3`` module (no ORM) to keep dependencies light. The
schema is intentionally simple and append-friendly: the audit log is the
source of truth for *why* decisions were made, positions/fills track state.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    stage         TEXT NOT NULL,
    event_id      TEXT,
    ticker        TEXT,
    kind          TEXT NOT NULL,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_id);
CREATE INDEX IF NOT EXISTS idx_audit_ticker ON audit_log(ticker);

CREATE TABLE IF NOT EXISTS positions (
    ticker        TEXT PRIMARY KEY,
    quantity      REAL NOT NULL,
    avg_price     REAL NOT NULL,
    stop_loss_pct REAL,
    take_profit_pct REAL,
    opened_at     TEXT NOT NULL,
    event_id      TEXT
);

CREATE TABLE IF NOT EXISTS fills (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    side          TEXT NOT NULL,
    quantity      REAL NOT NULL,
    price         REAL NOT NULL,
    fee           REAL NOT NULL,
    filled_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    event_id      TEXT,
    was_correct   INTEGER NOT NULL,
    realized_pnl_pct REAL NOT NULL,
    predicted_direction TEXT NOT NULL,
    stated_confidence REAL NOT NULL,
    summary       TEXT NOT NULL,
    detail        TEXT NOT NULL,
    tags          TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calibration (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    event_id      TEXT,
    stated_confidence REAL NOT NULL,
    was_correct   INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_signals (
    dedup_key     TEXT PRIMARY KEY,
    first_seen    TEXT NOT NULL
);
"""


class Database:
    """Thread-safe-ish SQLite wrapper.

    ``sqlite3`` connections are not shareable across threads by default; we
    guard access with a lock and open with ``check_same_thread=False`` so the
    scheduler thread and the dashboard thread can both read.
    """

    def __init__(self, path: str | Path = "xdd.db") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        is_memory = self.path == ":memory:"
        self._conn = sqlite3.connect(
            self.path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL" if not is_memory else "PRAGMA synchronous=OFF")
        self._conn.executescript(_SCHEMA)

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
