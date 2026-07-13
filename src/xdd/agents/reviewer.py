"""Reviewer agent — post-mortem on closed positions (the REFLECT stage)."""

from __future__ import annotations

import logging

from xdd.agents.llm import LLMClient, parse_json
from xdd.agents.prompts import REVIEWER_SYSTEM
from xdd.domain import Direction, Hypothesis, Lesson

log = logging.getLogger(__name__)


class Reviewer:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def review(
        self,
        hypothesis: Hypothesis,
        realized_pnl_pct: float,
        market_context: dict[str, float] | None = None,
    ) -> Lesson:
        ctx = ""
        if market_context:
            ctx = " ".join(f"{k}={v}" for k, v in market_context.items())
        prompt = (
            f"Original hypothesis for {hypothesis.ticker}:\n"
            f"  direction: {hypothesis.direction.value}\n"
            f"  confidence: {hypothesis.confidence}\n"
            f"  thesis: {hypothesis.thesis}\n\n"
            f"Outcome: realized_pnl_pct={realized_pnl_pct}\n"
            f"Market context at close: {ctx}\n\n"
            "Write the post-mortem lesson as JSON."
        )
        raw = self._llm.chat(REVIEWER_SYSTEM, prompt, json_mode=True)
        data = parse_json(raw)
        return Lesson(
            ticker=hypothesis.ticker,
            event_id=hypothesis.event_id,
            was_correct=bool(data.get("was_correct", realized_pnl_pct > 0)),
            realized_pnl_pct=realized_pnl_pct,
            predicted_direction=hypothesis.direction.value,
            stated_confidence=hypothesis.confidence,
            summary=str(data.get("summary", "")),
            detail=str(data.get("detail", "")),
            tags=list(data.get("tags", []) or []),
        )

    @staticmethod
    def outcome_was_correct(direction: Direction, realized_pnl_pct: float) -> bool:
        if direction == Direction.UP:
            return realized_pnl_pct > 0
        if direction == Direction.DOWN:
            return realized_pnl_pct < 0
        return abs(realized_pnl_pct) < 0.01
