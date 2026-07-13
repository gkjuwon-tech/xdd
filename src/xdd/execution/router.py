"""Order router: turns an approved Decision into a broker order + accounting.

Enforces the autonomy policy: paper trading executes autonomously, but real
money requires human approval. The approval gate is a callback so different
front-ends (CLI prompt, dashboard button, Slack) can plug in.
"""

from __future__ import annotations

import logging
from typing import Callable

from xdd.config import BrokerSettings
from xdd.domain import Action, Decision, Fill, OrderSide
from xdd.execution.broker_base import Broker
from xdd.execution.portfolio import PortfolioAccountant
from xdd.storage import AuditLog

log = logging.getLogger(__name__)

ApprovalCallback = Callable[[Decision], bool]


class OrderRouter:
    def __init__(
        self,
        broker: Broker,
        accountant: PortfolioAccountant,
        audit: AuditLog,
        broker_settings: BrokerSettings,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        self._broker = broker
        self._acct = accountant
        self._audit = audit
        self._cfg = broker_settings
        self._approve = approval_callback

    def execute(self, decision: Decision) -> Fill | None:
        if not decision.is_actionable:
            return None

        if self._requires_approval() and not self._approved(decision):
            self._audit.record(
                "act", "awaiting_human_approval", decision,
                event_id=decision.event_id, ticker=decision.ticker,
            )
            log.info("live order for %s awaiting human approval", decision.ticker)
            return None

        side = OrderSide.BUY if decision.action == Action.BUY else OrderSide.SELL
        qty = decision.target_quantity
        if qty <= 0:
            return None

        fill = self._broker.submit_market(decision.ticker, side, qty)
        if fill is None:
            self._audit.record(
                "act", "order_failed", decision,
                event_id=decision.event_id, ticker=decision.ticker,
            )
            return None

        realized = self._acct.apply_fill(fill, decision)
        self._audit.record(
            "act", "fill",
            {"fill": fill.model_dump(mode="json"), "realized_pnl": realized},
            event_id=decision.event_id, ticker=decision.ticker,
        )
        return fill

    def liquidate(self, ticker: str, reason: str) -> Fill | None:
        """Sell the entire position in ``ticker`` (used by stops and kill switch)."""
        pos = self._acct.snapshot().positions.get(ticker)
        if not pos or pos.quantity <= 0:
            return None
        fill = self._broker.submit_market(ticker, OrderSide.SELL, pos.quantity)
        if fill is None:
            return None
        realized = self._acct.apply_fill(fill)
        self._audit.record(
            "act", "liquidation",
            {"fill": fill.model_dump(mode="json"), "reason": reason, "realized_pnl": realized},
            ticker=ticker,
        )
        return fill

    # ------------------------------------------------------------------ gating
    def _requires_approval(self) -> bool:
        return self._cfg.live_trading and self._cfg.require_human_approval

    def _approved(self, decision: Decision) -> bool:
        if self._approve is None:
            return False  # deny by default when no approver is wired
        try:
            return bool(self._approve(decision))
        except Exception:  # noqa: BLE001
            return False
