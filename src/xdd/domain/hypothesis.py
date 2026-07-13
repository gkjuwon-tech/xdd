"""Hypotheses (Analyst output) and critiques (Skeptic output) — the ORIENT stage."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from xdd.domain.enums import Direction


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Hypothesis(BaseModel):
    """The Analyst's investment thesis about an event.

    Confidence is the agent's *self-assessed* probability that the predicted
    direction is correct. It is deliberately separate from position sizing —
    the risk engine decides how much (if anything) to bet on a given
    confidence, and the calibration tracker measures whether a stated 0.7
    actually resolves correctly ~70% of the time.
    """

    ticker: str
    event_id: str
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    horizon_hours: float = Field(gt=0, description="Expected time for the thesis to play out")
    thesis: str = Field(description="Natural-language reasoning")
    supporting_points: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list, description="Source URLs / ids")
    created_at: datetime = Field(default_factory=_utcnow)

    def with_confidence(self, confidence: float) -> "Hypothesis":
        return self.model_copy(update={"confidence": max(0.0, min(1.0, confidence))})


class Critique(BaseModel):
    """The Skeptic's adversarial review of a hypothesis.

    ``confidence_adjustment`` is added to the Analyst's confidence (typically
    negative). ``manipulation_suspected`` is a hard flag: when true, the risk
    engine refuses the trade regardless of confidence.
    """

    hypothesis_event_id: str
    counterpoints: list[str] = Field(default_factory=list)
    confidence_adjustment: float = Field(
        0.0, ge=-1.0, le=1.0, description="Added to Analyst confidence"
    )
    manipulation_suspected: bool = False
    already_priced_in: bool = False
    verdict: str = Field("", description="One-line summary of the skeptic's stance")
    created_at: datetime = Field(default_factory=_utcnow)
