"""The deterministic risk engine — the component with final veto power.

No matter how confident the Analyst is, a trade that violates a hard guardrail
is rejected here. This is intentionally boring, explicit, and non-LLM: the
survival of a tiny seed depends on rules that cannot be talked out of.

Spot, long-only by design (no shorting/leverage in the initial scope): a
bearish view on a held name becomes an exit; a bearish view on a name we don't
hold becomes HOLD.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xdd.config import RiskSettings
from xdd.domain import (
    Action,
    Critique,
    Decision,
    DecisionStatus,
    Direction,
    Hypothesis,
    Position,
)
from xdd.risk.calibration import CalibrationTracker
from xdd.risk.sizing import fractional_kelly


@dataclass
class PortfolioSnapshot:
    """Everything the risk engine needs to know about current portfolio state."""

    equity: float
    cash: float
    day_start_equity: float
    peak_equity: float
    positions: dict[str, Position] = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)

    @property
    def gross_exposure(self) -> float:
        invested = sum(
            pos.market_value(self.prices.get(t, pos.avg_price))
            for t, pos in self.positions.items()
        )
        return invested / self.equity if self.equity > 0 else 0.0

    @property
    def day_pnl_pct(self) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        return (self.equity - self.day_start_equity) / self.day_start_equity

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity


class RiskEngine:
    def __init__(self, settings: RiskSettings, calibration: CalibrationTracker | None = None) -> None:
        self._s = settings
        self._cal = calibration

    def decide(
        self,
        hypothesis: Hypothesis,
        critique: Critique,
        portfolio: PortfolioSnapshot,
    ) -> Decision:
        s = self._s
        ticker = hypothesis.ticker
        reasons: list[str] = []
        guardrails: list[str] = []

        # 1. Effective confidence = analyst - skeptic penalty, then calibrated.
        eff = max(0.0, hypothesis.confidence + critique.confidence_adjustment)
        if self._cal:
            eff = self._cal.calibrate(eff)
        eff = round(eff, 4)
        reasons.append(
            f"confidence: analyst {hypothesis.confidence:.2f}"
            f" {critique.confidence_adjustment:+.2f} skeptic -> effective {eff:.2f}"
        )

        def reject(reason: str, guardrail: str) -> Decision:
            guardrails.append(guardrail)
            reasons.append(reason)
            return Decision(
                ticker=ticker, event_id=hypothesis.event_id, action=Action.HOLD,
                status=DecisionStatus.REJECTED, effective_confidence=eff,
                reasons=reasons, guardrail_hits=guardrails,
            )

        def no_action(reason: str) -> Decision:
            reasons.append(reason)
            return Decision(
                ticker=ticker, event_id=hypothesis.event_id, action=Action.HOLD,
                status=DecisionStatus.NO_ACTION, effective_confidence=eff,
                reasons=reasons, guardrail_hits=guardrails,
            )

        existing = portfolio.positions.get(ticker)

        # 2. Hard vetoes (cannot be overridden by confidence).
        if critique.manipulation_suspected:
            return reject("skeptic flagged suspected manipulation", "manipulation")

        if portfolio.drawdown_pct >= s.max_drawdown_pct:
            return reject(
                f"max drawdown breached ({portfolio.drawdown_pct:.1%} >= {s.max_drawdown_pct:.0%})",
                "max_drawdown",
            )

        if portfolio.day_pnl_pct <= -s.daily_loss_limit_pct:
            return reject(
                f"daily loss limit hit ({portfolio.day_pnl_pct:.1%})", "daily_loss_limit"
            )

        # 3. Map direction to a long-only action.
        if hypothesis.direction == Direction.DOWN:
            if existing and existing.quantity > 0:
                return self._exit_decision(ticker, hypothesis, eff, reasons, guardrails, existing)
            return no_action("bearish view but no position to exit (no shorting)")

        if hypothesis.direction == Direction.NEUTRAL:
            return no_action("neutral direction — standing aside")

        # direction == UP -> consider a BUY entry.
        if eff < s.min_confidence_to_trade:
            return no_action(
                f"confidence {eff:.2f} below trade threshold {s.min_confidence_to_trade:.2f}"
            )

        return self._entry_decision(ticker, hypothesis, eff, reasons, guardrails, portfolio, existing)

    # ------------------------------------------------------------------ entry
    def _entry_decision(
        self, ticker, hypothesis, eff, reasons, guardrails, portfolio, existing
    ) -> Decision:
        s = self._s
        price = portfolio.prices.get(ticker)
        if not price or price <= 0:
            reasons.append("no price available")
            return Decision(
                ticker=ticker, event_id=hypothesis.event_id, action=Action.HOLD,
                status=DecisionStatus.NO_ACTION, effective_confidence=eff,
                reasons=reasons, guardrail_hits=guardrails,
            )

        tp = s.default_take_profit_pct
        sl = s.default_stop_loss_pct

        # Fee viability: expected edge must clear the round-trip fee.
        expected_edge = eff * tp - (1 - eff) * sl
        round_trip_fee = 2 * s.fee_pct
        reasons.append(f"expected edge {expected_edge:+.3f} vs round-trip fee {round_trip_fee:.3f}")
        if expected_edge <= round_trip_fee:
            reasons.append("edge does not clear fees — standing aside")
            return Decision(
                ticker=ticker, event_id=hypothesis.event_id, action=Action.HOLD,
                status=DecisionStatus.NO_ACTION, effective_confidence=eff,
                reasons=reasons, guardrail_hits=guardrails,
            )

        # Fractional-Kelly notional, then apply hard caps.
        kelly_frac = fractional_kelly(eff, tp, sl, s.kelly_fraction)
        target = kelly_frac * portfolio.equity
        reasons.append(f"kelly fraction {kelly_frac:.3f} -> raw target {target:.0f}")

        # Per-ticker exposure cap (accounting for any existing position).
        existing_val = existing.market_value(price) if existing else 0.0
        pos_cap = s.max_position_pct * portfolio.equity - existing_val
        if pos_cap <= 0:
            guardrails.append("position_cap")
            reasons.append("already at per-ticker exposure cap")
            return self._no_action(ticker, hypothesis, eff, reasons, guardrails)
        target = min(target, pos_cap)

        # Cash floor + gross-exposure cap.
        deployable_cash = portfolio.cash - s.min_cash_pct * portfolio.equity
        gross_room = (s.max_gross_exposure_pct - portfolio.gross_exposure) * portfolio.equity
        target = min(target, max(0.0, deployable_cash), max(0.0, gross_room))
        if deployable_cash <= 0:
            guardrails.append("cash_floor")
        if gross_room <= 0:
            guardrails.append("gross_exposure")

        if target < s.min_order_notional:
            reasons.append(
                f"sized notional {target:.0f} below min order {s.min_order_notional:.0f}"
            )
            return self._no_action(ticker, hypothesis, eff, reasons, guardrails)

        qty = target / price
        reasons.append(f"approved buy: notional {target:.0f}, qty {qty:.4f} @ {price:.2f}")
        return Decision(
            ticker=ticker, event_id=hypothesis.event_id, action=Action.BUY,
            status=DecisionStatus.APPROVED, effective_confidence=eff,
            target_notional=round(target, 2), target_quantity=round(qty, 6),
            stop_loss_pct=sl, take_profit_pct=tp,
            reasons=reasons, guardrail_hits=guardrails,
        )

    # ------------------------------------------------------------------- exit
    def _exit_decision(self, ticker, hypothesis, eff, reasons, guardrails, existing) -> Decision:
        reasons.append("bearish view on held position — exiting in full")
        return Decision(
            ticker=ticker, event_id=hypothesis.event_id, action=Action.SELL,
            status=DecisionStatus.APPROVED, effective_confidence=eff,
            target_quantity=existing.quantity, reasons=reasons, guardrail_hits=guardrails,
        )

    def _no_action(self, ticker, hypothesis, eff, reasons, guardrails) -> Decision:
        return Decision(
            ticker=ticker, event_id=hypothesis.event_id, action=Action.HOLD,
            status=DecisionStatus.NO_ACTION, effective_confidence=eff,
            reasons=reasons, guardrail_hits=guardrails,
        )
