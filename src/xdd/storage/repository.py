"""Typed accessors over the SQLite tables (positions, fills, lessons, calibration)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from xdd.domain import Fill, Lesson, Position
from xdd.storage.db import Database


class Repository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------ dedup
    def is_seen(self, dedup_key: str) -> bool:
        return self._db.query_one(
            "SELECT 1 FROM seen_signals WHERE dedup_key = ?", (dedup_key,)
        ) is not None

    def mark_seen(self, dedup_key: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO seen_signals (dedup_key, first_seen) VALUES (?, ?)",
            (dedup_key, datetime.now(timezone.utc).isoformat()),
        )

    # --------------------------------------------------------------- positions
    def get_position(self, ticker: str) -> Position | None:
        r = self._db.query_one("SELECT * FROM positions WHERE ticker = ?", (ticker,))
        if not r:
            return None
        return Position(
            ticker=r["ticker"],
            quantity=r["quantity"],
            avg_price=r["avg_price"],
            stop_loss_pct=r["stop_loss_pct"],
            take_profit_pct=r["take_profit_pct"],
            opened_at=datetime.fromisoformat(r["opened_at"]),
            event_id=r["event_id"],
        )

    def all_positions(self) -> list[Position]:
        rows = self._db.query("SELECT ticker FROM positions WHERE quantity <> 0")
        return [p for p in (self.get_position(r["ticker"]) for r in rows) if p]

    def upsert_position(self, pos: Position) -> None:
        if abs(pos.quantity) < 1e-12:
            self._db.execute("DELETE FROM positions WHERE ticker = ?", (pos.ticker,))
            return
        self._db.execute(
            "INSERT INTO positions (ticker, quantity, avg_price, stop_loss_pct,"
            " take_profit_pct, opened_at, event_id) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(ticker) DO UPDATE SET quantity=excluded.quantity,"
            " avg_price=excluded.avg_price, stop_loss_pct=excluded.stop_loss_pct,"
            " take_profit_pct=excluded.take_profit_pct, event_id=excluded.event_id",
            (
                pos.ticker,
                pos.quantity,
                pos.avg_price,
                pos.stop_loss_pct,
                pos.take_profit_pct,
                pos.opened_at.isoformat(),
                pos.event_id,
            ),
        )

    def delete_position(self, ticker: str) -> None:
        self._db.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))

    # ------------------------------------------------------------------- fills
    def record_fill(self, fill: Fill) -> None:
        self._db.execute(
            "INSERT INTO fills (order_id, ticker, side, quantity, price, fee, filled_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                fill.order_id,
                fill.ticker,
                fill.side.value,
                fill.quantity,
                fill.price,
                fill.fee,
                fill.filled_at.isoformat(),
            ),
        )

    def fills_for(self, ticker: str) -> list[Fill]:
        from xdd.domain import OrderSide

        rows = self._db.query(
            "SELECT * FROM fills WHERE ticker = ? ORDER BY id ASC", (ticker,)
        )
        return [
            Fill(
                order_id=r["order_id"],
                ticker=r["ticker"],
                side=OrderSide(r["side"]),
                quantity=r["quantity"],
                price=r["price"],
                fee=r["fee"],
                filled_at=datetime.fromisoformat(r["filled_at"]),
            )
            for r in rows
        ]

    # ----------------------------------------------------------------- lessons
    def add_lesson(self, lesson: Lesson) -> None:
        self._db.execute(
            "INSERT INTO lessons (ticker, event_id, was_correct, realized_pnl_pct,"
            " predicted_direction, stated_confidence, summary, detail, tags, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lesson.ticker,
                lesson.event_id,
                int(lesson.was_correct),
                lesson.realized_pnl_pct,
                lesson.predicted_direction,
                lesson.stated_confidence,
                lesson.summary,
                lesson.detail,
                json.dumps(lesson.tags),
                lesson.created_at.isoformat(),
            ),
        )

    def all_lessons(self) -> list[Lesson]:
        rows = self._db.query("SELECT * FROM lessons ORDER BY id DESC")
        return [
            Lesson(
                ticker=r["ticker"],
                event_id=r["event_id"],
                was_correct=bool(r["was_correct"]),
                realized_pnl_pct=r["realized_pnl_pct"],
                predicted_direction=r["predicted_direction"],
                stated_confidence=r["stated_confidence"],
                summary=r["summary"],
                detail=r["detail"],
                tags=json.loads(r["tags"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------- calibration
    def record_calibration(
        self, ticker: str, event_id: str | None, confidence: float, correct: bool
    ) -> None:
        self._db.execute(
            "INSERT INTO calibration (ticker, event_id, stated_confidence, was_correct,"
            " created_at) VALUES (?, ?, ?, ?, ?)",
            (
                ticker,
                event_id,
                confidence,
                int(correct),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def calibration_records(self) -> list[tuple[float, bool]]:
        rows = self._db.query(
            "SELECT stated_confidence, was_correct FROM calibration ORDER BY id ASC"
        )
        return [(r["stated_confidence"], bool(r["was_correct"])) for r in rows]

    # ---------------------------------------------------------------------- kv
    def get_kv(self, key: str, default: str | None = None) -> str | None:
        r = self._db.query_one("SELECT value FROM kv WHERE key = ?", (key,))
        return r["value"] if r else default

    def set_kv(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
