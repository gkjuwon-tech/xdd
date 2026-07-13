"""Confidence calibration.

The agent's *self-assessed* confidence is only trustworthy if a stated 0.7
actually resolves correct ~70% of the time. This tracker measures that from
historical outcomes and returns a discount factor so the risk engine can shrink
over-stated confidence before sizing. It is the mechanism behind the plan's
"neutralize over-confidence" goal.
"""

from __future__ import annotations

from xdd.storage import Repository


class CalibrationTracker:
    def __init__(self, repo: Repository, min_samples: int = 15) -> None:
        self._repo = repo
        self._min_samples = min_samples

    def record(self, ticker: str, event_id: str | None, confidence: float, correct: bool) -> None:
        self._repo.record_calibration(ticker, event_id, confidence, correct)

    def reliability(self) -> float | None:
        """Empirical hit-rate among predictions where stated confidence >= 0.5.

        Returns ``None`` until enough samples exist to be meaningful.
        """
        records = self._repo.calibration_records()
        confident = [(c, ok) for c, ok in records if c >= 0.5]
        if len(confident) < self._min_samples:
            return None
        hits = sum(1 for _, ok in confident if ok)
        return hits / len(confident)

    def calibrate(self, stated_confidence: float) -> float:
        """Adjust a stated confidence toward the empirically observed hit-rate.

        Blends the stated value with observed reliability. Before enough data
        exists, applies a mild prudence haircut so a cold-start agent does not
        bet the stated confidence at face value.
        """
        reliability = self.reliability()
        if reliability is None:
            return stated_confidence * 0.9  # cold-start prudence
        # Shrink stated confidence toward observed reliability.
        blended = 0.5 * stated_confidence + 0.5 * reliability
        # Never let calibration *inflate* a low-confidence call.
        return min(stated_confidence, max(0.0, blended))
