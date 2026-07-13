"""Broker interface."""

from __future__ import annotations

from typing import Protocol

from xdd.domain import Fill, OrderSide


class Broker(Protocol):
    name: str

    def submit_market(self, ticker: str, side: OrderSide, quantity: float) -> Fill | None:
        """Submit a market order and return the resulting fill (or None on failure)."""
        ...

    def get_price(self, ticker: str) -> float | None:
        ...
