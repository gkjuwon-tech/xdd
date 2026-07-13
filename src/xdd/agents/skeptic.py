"""Skeptic agent — adversarially reviews a Hypothesis (over-confidence guard)."""

from __future__ import annotations

import logging

from xdd.agents.llm import LLMClient, parse_json
from xdd.agents.prompts import SKEPTIC_SYSTEM
from xdd.domain import Critique, Event, Hypothesis

log = logging.getLogger(__name__)


class Skeptic:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def critique(self, event: Event, hypothesis: Hypothesis) -> Critique:
        prompt = (
            f"{event.summary()}\n\n"
            f"Analyst hypothesis:\n"
            f"  direction: {hypothesis.direction.value}\n"
            f"  confidence: {hypothesis.confidence}\n"
            f"  thesis: {hypothesis.thesis}\n"
            f"  supporting: {hypothesis.supporting_points}\n\n"
            "Attack this hypothesis. Return JSON."
        )
        raw = self._llm.chat(SKEPTIC_SYSTEM, prompt, json_mode=True)
        data = parse_json(raw)
        adjustment = float(data.get("confidence_adjustment", 0.0) or 0.0)
        # The skeptic can only *lower* confidence.
        adjustment = max(-1.0, min(0.0, adjustment))
        return Critique(
            hypothesis_event_id=hypothesis.event_id,
            counterpoints=list(data.get("counterpoints", []) or []),
            confidence_adjustment=adjustment,
            manipulation_suspected=bool(data.get("manipulation_suspected", False)),
            already_priced_in=bool(data.get("already_priced_in", False)),
            verdict=str(data.get("verdict", "")),
        )
