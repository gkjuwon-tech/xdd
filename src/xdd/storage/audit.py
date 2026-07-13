"""Append-only audit log — the observability backbone.

Every meaningful step (signal ingested, event formed, hypothesis generated,
critique attached, decision made, order filled, position reviewed) is written
here with its full payload, so any trade can be reconstructed end-to-end. This
is a P0 success criterion: *why* the agent acted must always be recoverable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from xdd.storage.db import Database


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    raise TypeError(f"not serializable: {type(obj)}")


class AuditLog:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        stage: str,
        kind: str,
        payload: Any,
        *,
        event_id: str | None = None,
        ticker: str | None = None,
    ) -> None:
        if isinstance(payload, BaseModel):
            data = payload.model_dump(mode="json")
        else:
            data = payload
        self._db.execute(
            "INSERT INTO audit_log (ts, stage, event_id, ticker, kind, payload)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                stage,
                event_id,
                ticker,
                kind,
                json.dumps(data, default=_default),
            ),
        )

    def recent(self, limit: int = 100) -> list[dict]:
        rows = self._db.query(
            "SELECT ts, stage, event_id, ticker, kind, payload FROM audit_log"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        out = []
        for r in rows:
            out.append(
                {
                    "ts": r["ts"],
                    "stage": r["stage"],
                    "event_id": r["event_id"],
                    "ticker": r["ticker"],
                    "kind": r["kind"],
                    "payload": json.loads(r["payload"]),
                }
            )
        return out

    def for_event(self, event_id: str) -> list[dict]:
        rows = self._db.query(
            "SELECT ts, stage, kind, payload FROM audit_log WHERE event_id = ?"
            " ORDER BY id ASC",
            (event_id,),
        )
        return [
            {
                "ts": r["ts"],
                "stage": r["stage"],
                "kind": r["kind"],
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]
