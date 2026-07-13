"""Decisions (risk engine), orders, fills, and positions — the DECIDE/ACT stages."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from xdd.domain.enums import Action, DecisionStatus, OrderSide, OrderStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Decision(BaseModel):
    """The deterministic risk engine's ruling on a (hypothesis, critique) pair.

    This is the object with veto power. Even a maximally confident hypothesis
    yields ``status=REJECTED`` if it violates a hard guardrail. Every decision
    records *why* it was made so the audit log can reconstruct the reasoning.
    """

    ticker: str
    event_id: str
    action: Action
    status: DecisionStatus
    effective_confidence: float = Field(ge=0.0, le=1.0)
    target_notional: float = Field(0.0, description="Currency amount to deploy")
    target_quantity: float = 0.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    reasons: list[str] = Field(default_factory=list)
    guardrail_hits: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def is_actionable(self) -> bool:
        return self.status == DecisionStatus.APPROVED and self.action != Action.HOLD


class Order(BaseModel):
    ticker: str
    side: OrderSide
    quantity: float
    status: OrderStatus = OrderStatus.PENDING
    broker_order_id: str | None = None
    limit_price: float | None = None
    decision_event_id: str | None = None
    submitted_at: datetime = Field(default_factory=_utcnow)


class Fill(BaseModel):
    order_id: str
    ticker: str
    side: OrderSide
    quantity: float
    price: float
    fee: float = 0.0
    filled_at: datetime = Field(default_factory=_utcnow)

    @property
    def notional(self) -> float:
        return self.quantity * self.price


class Position(BaseModel):
    """A currently-held position, tracked with average cost basis."""

    ticker: str
    quantity: float = 0.0
    avg_price: float = 0.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    opened_at: datetime = Field(default_factory=_utcnow)
    event_id: str | None = None

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_price

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_price) * self.quantity

    def unrealized_pnl_pct(self, price: float) -> float:
        if self.avg_price == 0:
            return 0.0
        return (price - self.avg_price) / self.avg_price
