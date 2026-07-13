"""Long-term memory: lessons learned from closed positions (the REFLECT stage)."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Lesson(BaseModel):
    """A single learning extracted by the Reviewer after a position closes.

    Lessons are stored in the vector memory and retrieved when the Analyst
    reasons about a similar future event, closing the learning loop.
    """

    ticker: str
    event_id: str | None = None
    was_correct: bool
    realized_pnl_pct: float
    predicted_direction: str
    stated_confidence: float
    summary: str = Field(description="One-line takeaway")
    detail: str = Field("", description="What was right/wrong and why")
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def text(self) -> str:
        return f"{self.summary} {self.detail} {' '.join(self.tags)}".strip()
