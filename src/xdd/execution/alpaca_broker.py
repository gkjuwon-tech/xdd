"""Alpaca broker adapter (paper or live) via REST.

Kept import-light: it only calls out when actually used. Live trading is gated
by configuration and, at the orchestrator level, by human approval.
"""

from __future__ import annotations

import logging
import uuid

import httpx

from xdd.domain import Fill, OrderSide

log = logging.getLogger(__name__)


class AlpacaBroker:
    name = "alpaca"

    def __init__(self, key_id: str, secret_key: str, base_url: str) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._data_base = "https://data.alpaca.markets/v2"

    def get_price(self, ticker: str) -> float | None:
        url = f"{self._data_base}/stocks/{ticker}/trades/latest"
        try:
            resp = httpx.get(url, headers=self._headers, timeout=15)
            resp.raise_for_status()
            return float(resp.json()["trade"]["p"])
        except Exception as exc:  # noqa: BLE001
            log.warning("alpaca price fetch failed for %s: %s", ticker, exc)
            return None

    def submit_market(self, ticker: str, side: OrderSide, quantity: float) -> Fill | None:
        payload = {
            "symbol": ticker,
            "qty": str(quantity),
            "side": side.value,
            "type": "market",
            "time_in_force": "day",
        }
        try:
            resp = httpx.post(
                f"{self._base}/v2/orders", json=payload, headers=self._headers, timeout=20
            )
            resp.raise_for_status()
            order = resp.json()
        except Exception as exc:  # noqa: BLE001
            log.error("alpaca order failed for %s: %s", ticker, exc)
            return None
        filled_price = order.get("filled_avg_price") or self.get_price(ticker)
        if filled_price is None:
            return None
        return Fill(
            order_id=order.get("id", f"alpaca-{uuid.uuid4().hex[:8]}"),
            ticker=ticker,
            side=side,
            quantity=float(order.get("filled_qty") or quantity),
            price=float(filled_price),
            fee=0.0,
        )
