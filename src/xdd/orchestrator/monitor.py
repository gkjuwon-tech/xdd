"""Position monitor: exits (stop/take/kill) and the REFLECT learning loop.

Runs each cycle. For every open position it checks stop-loss / take-profit /
kill-switch conditions, liquidates when triggered, and then hands the closed
trade to the Reviewer to extract a lesson and record a calibration data point —
closing the observe → ... → reflect loop.
"""

from __future__ import annotations

import json
import logging

from xdd.agents import Reviewer
from xdd.collectors.price import MarketDataCollector
from xdd.domain import Direction, Hypothesis
from xdd.execution import OrderRouter, PortfolioAccountant
from xdd.memory import MemoryStore
from xdd.observability import KillSwitch
from xdd.risk import CalibrationTracker
from xdd.storage import AuditLog, Repository

log = logging.getLogger(__name__)


def hyp_key(ticker: str) -> str:
    return f"open_hyp:{ticker}"


class PositionMonitor:
    def __init__(
        self,
        repo: Repository,
        accountant: PortfolioAccountant,
        router: OrderRouter,
        reviewer: Reviewer,
        calibration: CalibrationTracker,
        memory: MemoryStore,
        market: MarketDataCollector,
        kill_switch: KillSwitch,
        audit: AuditLog,
    ) -> None:
        self._repo = repo
        self._acct = accountant
        self._router = router
        self._reviewer = reviewer
        self._cal = calibration
        self._memory = memory
        self._market = market
        self._kill = kill_switch
        self._audit = audit

    def record_open_hypothesis(self, hypothesis: Hypothesis) -> None:
        """Persist the thesis behind an opened position for later post-mortem."""
        self._repo.set_kv(
            hyp_key(hypothesis.ticker),
            json.dumps(
                {
                    "ticker": hypothesis.ticker,
                    "event_id": hypothesis.event_id,
                    "direction": hypothesis.direction.value,
                    "confidence": hypothesis.confidence,
                    "horizon_hours": hypothesis.horizon_hours,
                    "thesis": hypothesis.thesis,
                }
            ),
        )

    def run(self) -> list[dict]:
        exits: list[dict] = []
        snap = self._acct.snapshot()
        for ticker, pos in list(snap.positions.items()):
            price = snap.prices.get(ticker) or self._acct._prices.get_price(ticker)
            if price is None:
                continue
            pnl_pct = pos.unrealized_pnl_pct(price)
            reason = self._exit_reason(pos, pnl_pct)
            if reason is None:
                continue
            fill = self._router.liquidate(ticker, reason)
            if fill is None:
                continue
            realized_pct = pnl_pct
            self._reflect(ticker, realized_pct)
            exits.append({"ticker": ticker, "reason": reason, "realized_pct": round(realized_pct, 4)})
        return exits

    def _exit_reason(self, pos, pnl_pct: float) -> str | None:
        if self._kill.engaged:
            return f"kill_switch:{self._kill.reason}"
        if pos.take_profit_pct is not None and pnl_pct >= pos.take_profit_pct:
            return f"take_profit ({pnl_pct:+.1%})"
        if pos.stop_loss_pct is not None and pnl_pct <= -pos.stop_loss_pct:
            return f"stop_loss ({pnl_pct:+.1%})"
        return None

    def _reflect(self, ticker: str, realized_pct: float) -> None:
        raw = self._repo.get_kv(hyp_key(ticker))
        if not raw:
            return
        data = json.loads(raw)
        hyp = Hypothesis(
            ticker=data["ticker"],
            event_id=data.get("event_id", ""),
            direction=Direction(data.get("direction", "up")),
            confidence=float(data.get("confidence", 0.5)),
            horizon_hours=float(data.get("horizon_hours", 48)),
            thesis=data.get("thesis", ""),
        )
        market = self._market.snapshot(ticker)
        lesson = self._reviewer.review(hyp, realized_pct, market)
        self._memory.add(lesson)
        correct = self._reviewer.outcome_was_correct(hyp.direction, realized_pct)
        self._cal.record(ticker, hyp.event_id, hyp.confidence, correct)
        self._audit.record(
            "reflect", "lesson", lesson, event_id=hyp.event_id, ticker=ticker
        )
        self._repo.set_kv(hyp_key(ticker), "")
