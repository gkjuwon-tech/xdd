"""Lightweight lexicon sentiment scorer.

A dependency-free, finance-tuned lexicon gives a fast first-pass sentiment in
[-1, 1]. The LLM Analyst does the nuanced reading; this score is only used for
aggregation, ranking, and the volume/novelty features.
"""

from __future__ import annotations

import re

_POSITIVE = {
    "beat", "beats", "surge", "surges", "soar", "rally", "bullish", "upgrade",
    "upgraded", "record", "growth", "profit", "gains", "outperform", "buy",
    "strong", "breakout", "momentum", "raises", "raised", "expands", "wins",
    "approval", "approved", "partnership", "acquire", "acquisition", "beat.",
}
_NEGATIVE = {
    "miss", "misses", "plunge", "plunges", "crash", "bearish", "downgrade",
    "downgraded", "loss", "losses", "lawsuit", "probe", "investigation",
    "recall", "cut", "cuts", "warning", "warns", "weak", "selloff", "fraud",
    "bankruptcy", "default", "layoffs", "decline", "slump", "fell", "drops",
}
_NEGATORS = {"not", "no", "never", "without", "fails", "failed"}

_WORD = re.compile(r"[a-zA-Z']+")


def score_sentiment(text: str) -> float:
    """Return sentiment in [-1, 1]; 0 when neutral or no signal words hit."""
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return 0.0
    score = 0
    hits = 0
    for i, w in enumerate(words):
        val = 0
        if w in _POSITIVE:
            val = 1
        elif w in _NEGATIVE:
            val = -1
        if val:
            if i > 0 and words[i - 1] in _NEGATORS:
                val = -val
            score += val
            hits += 1
    if hits == 0:
        return 0.0
    return max(-1.0, min(1.0, score / (hits + 1)))
