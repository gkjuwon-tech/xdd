"""Spam / bot / pump-and-dump detection.

Following the plan's risk section, signals that look like coordinated
manipulation or low-quality spam are dropped *before* they reach the Analyst.
This is heuristic and deliberately conservative: it flags the obvious
pump-and-dump language and throwaway-account patterns, not subtle cases (the
Skeptic agent catches the rest).
"""

from __future__ import annotations

import re

from xdd.domain import Signal, SignalSource

_PUMP_PHRASES = [
    "to the moon", "🚀🚀", "guaranteed", "can't lose", "cant lose",
    "next 100x", "10x guaranteed", "pump", "load up now", "before it explodes",
    "get in now", "easy money", "you will regret", "financial advice not",
]
_PROMO = re.compile(r"(join|dm me|telegram|discord\.gg|whatsapp|signal group)", re.I)


class ManipulationFilter:
    def __init__(self, min_score: float = 3.0) -> None:
        # Minimum Reddit score for a social post to be trusted at all.
        self._min_score = min_score

    def is_suspicious(self, signal: Signal) -> tuple[bool, str]:
        """Return (suspicious, reason)."""
        text = signal.text.lower()

        for phrase in _PUMP_PHRASES:
            if phrase in text:
                return True, f"pump phrase: {phrase!r}"

        if _PROMO.search(text):
            return True, "promotional / off-platform recruitment"

        # Excessive emoji / all-caps hype is a weak but useful bot tell.
        if _hype_ratio(signal.title) > 0.5 and len(signal.title) > 20:
            return True, "excessive hype formatting"

        if signal.source == SignalSource.REDDIT:
            score = signal.metrics.get("score", 0.0)
            ratio = signal.metrics.get("upvote_ratio", 1.0)
            if score < self._min_score and ratio < 0.6:
                return True, "low-engagement, contested social post"

        return False, ""

    def filter(self, signals: list[Signal]) -> tuple[list[Signal], list[tuple[Signal, str]]]:
        kept: list[Signal] = []
        dropped: list[tuple[Signal, str]] = []
        for s in signals:
            suspicious, reason = self.is_suspicious(s)
            if suspicious:
                dropped.append((s, reason))
            else:
                kept.append(s)
        return kept, dropped


def _hype_ratio(text: str) -> float:
    if not text:
        return 0.0
    caps = sum(1 for c in text if c.isupper())
    letters = sum(1 for c in text if c.isalpha()) or 1
    return caps / letters
