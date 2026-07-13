"""Fully-local paper broker.

Fills market orders at the current price plus a small slippage and a fee, with
no external dependency. This is the default backend and the one used for the
mandatory paper-trading validation phase before any real capital.
"""

from __future__ import annotations

import uuid

from xdd.collectors.price import PriceProvider
from xdd.domain import Fill, OrderSide


class PaperBroker:
    name = "paper"

    def __init__(
        self, price_provider: PriceProvider, *, fee_pct: float = 0.001, slippage_pct: float = 0.0005
    ) -> None:
        self._prices = price_provider
        self._fee_pct = fee_pct
        self._slippage_pct = slippage_pct

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get_price(ticker)

    def submit_market(self, ticker: str, side: OrderSide, quantity: float) -> Fill | None:
        price = self._prices.get_price(ticker)
        if price is None or price <= 0 or quantity <= 0:
            return None
        # Buyers cross the spread up, sellers down.
        slip = self._slippage_pct if side == OrderSide.BUY else -self._slippage_pct
        exec_price = price * (1 + slip)
        fee = exec_price * quantity * self._fee_pct
        return Fill(
            order_id=f"paper-{uuid.uuid4().hex[:10]}",
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=round(exec_price, 6),
            fee=round(fee, 6),
        )
