"""Analyst agent — turns an Event into a Hypothesis (the ORIENT stage)."""

from __future__ import annotations

import logging

from xdd.agents.llm import LLMClient, parse_json
from xdd.agents.prompts import ANALYST_SYSTEM
from xdd.domain import Direction, Event, Hypothesis
from xdd.memory import MemoryStore

log = logging.getLogger(__name__)


class Analyst:
    def __init__(self, llm: LLMClient, memory: MemoryStore | None = None) -> None:
        self._llm = llm
        self._memory = memory

    def analyze(self, event: Event) -> Hypothesis:
        prompt = self._build_prompt(event)
        raw = self._llm.chat(ANALYST_SYSTEM, prompt, json_mode=True)
        data = parse_json(raw)
        return self._to_hypothesis(event, data)

    def _build_prompt(self, event: Event) -> str:
        parts = [event.summary()]
        # Inject relevant prior lessons so the agent learns across sessions.
        if self._memory:
            lessons = self._memory.retrieve(event.summary(), ticker=event.ticker, k=3)
            if lessons:
                parts.append("\nRelevant lessons from past trades:")
                for les in lessons:
                    verdict = "correct" if les.was_correct else "wrong"
                    parts.append(f"- ({verdict}, {les.realized_pnl_pct:+.1%}) {les.summary}")
        parts.append("\nReturn your hypothesis as JSON.")
        return "\n".join(parts)

    def _to_hypothesis(self, event: Event, data: dict) -> Hypothesis:
        try:
            direction = Direction(str(data.get("direction", "neutral")).lower())
        except ValueError:
            direction = Direction.NEUTRAL
        return Hypothesis(
            ticker=event.ticker,
            event_id=event.event_id,
            direction=direction,
            confidence=_clamp(float(data.get("confidence", 0.3))),
            horizon_hours=float(data.get("horizon_hours", 48) or 48),
            thesis=str(data.get("thesis", "")),
            supporting_points=list(data.get("supporting_points", []) or []),
            risk_factors=list(data.get("risk_factors", []) or []),
            citations=list(data.get("citations", []) or []),
        )


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))
