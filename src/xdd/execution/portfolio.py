"""Portfolio accounting: cash, positions, equity, and fill application.

Cash and the day-start / peak-equity marks live in the ``kv`` table so state
survives restarts (the container is ephemeral; anything worth keeping is
persisted). Positions live in the ``positions`` table. This module is the
single place that mutates portfolio state, keeping accounting consistent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from xdd.collectors.price import PriceProvider
from xdd.domain import Decision, Fill, OrderSide, Position
from xdd.risk import PortfolioSnapshot
from xdd.storage import Repository

_CASH = "cash"
_PEAK = "peak_equity"
_DAY_START = "day_start_equity"
_DAY_DATE = "day_start_date"


class PortfolioAccountant:
    def __init__(self, repo: Repository, prices: PriceProvider, seed_capital: float) -> None:
        self._repo = repo
        self._prices = prices
        if self._repo.get_kv(_CASH) is None:
            self._repo.set_kv(_CASH, str(seed_capital))
            self._repo.set_kv(_PEAK, str(seed_capital))
            self._repo.set_kv(_DAY_START, str(seed_capital))
            self._repo.set_kv(_DAY_DATE, _today())

    # --------------------------------------------------------------- accessors
    @property
    def cash(self) -> float:
        return float(self._repo.get_kv(_CASH, "0") or 0)

    def _set_cash(self, value: float) -> None:
        self._repo.set_kv(_CASH, str(value))

    def prices_for(self, tickers: list[str]) -> dict[str, float]:
        out = {}
        for t in tickers:
            p = self._prices.get_price(t)
            if p is not None:
                out[t] = p
        return out

    def equity(self) -> float:
        total = self.cash
        for pos in self._repo.all_positions():
            price = self._prices.get_price(pos.ticker) or pos.avg_price
            total += pos.market_value(price)
        return total

    def snapshot(self) -> PortfolioSnapshot:
        positions = {p.ticker: p for p in self._repo.all_positions()}
        prices = self.prices_for(list(positions))
        equity = self.cash + sum(
            pos.market_value(prices.get(t, pos.avg_price)) for t, pos in positions.items()
        )
        self._maybe_roll_day(equity)
        peak = max(float(self._repo.get_kv(_PEAK, "0") or 0), equity)
        self._repo.set_kv(_PEAK, str(peak))
        return PortfolioSnapshot(
            equity=equity,
            cash=self.cash,
            day_start_equity=float(self._repo.get_kv(_DAY_START, str(equity)) or equity),
            peak_equity=peak,
            positions=positions,
            prices=prices,
        )

    def snapshot_with_price(self, ticker: str) -> PortfolioSnapshot:
        """Snapshot that guarantees a price for ``ticker`` is present."""
        snap = self.snapshot()
        if ticker not in snap.prices:
            price = self._prices.get_price(ticker)
            if price is not None:
                snap.prices[ticker] = price
        return snap

    # ---------------------------------------------------------------- mutation
    def apply_fill(self, fill: Fill, decision: Decision | None = None) -> float:
        """Apply a fill to cash + positions. Returns realized pnl (0 for buys)."""
        self._repo.record_fill(fill)
        pos = self._repo.get_position(fill.ticker)
        realized = 0.0

        if fill.side == OrderSide.BUY:
            self._set_cash(self.cash - fill.notional - fill.fee)
            if pos and pos.quantity > 0:
                new_qty = pos.quantity + fill.quantity
                new_cost = pos.cost_basis + fill.notional
                pos.quantity = new_qty
                pos.avg_price = new_cost / new_qty
            else:
                pos = Position(
                    ticker=fill.ticker,
                    quantity=fill.quantity,
                    avg_price=fill.price,
                    opened_at=datetime.now(timezone.utc),
                    event_id=decision.event_id if decision else None,
                )
            if decision:
                pos.stop_loss_pct = decision.stop_loss_pct
                pos.take_profit_pct = decision.take_profit_pct
            self._repo.upsert_position(pos)
        else:  # SELL
            if pos and pos.quantity > 0:
                sell_qty = min(fill.quantity, pos.quantity)
                realized = (fill.price - pos.avg_price) * sell_qty - fill.fee
                pos.quantity -= sell_qty
                self._repo.upsert_position(pos)
            self._set_cash(self.cash + fill.notional - fill.fee)

        return realized

    def start_new_day(self) -> None:
        self._repo.set_kv(_DAY_START, str(self.equity()))
        self._repo.set_kv(_DAY_DATE, _today())

    def _maybe_roll_day(self, equity: float) -> None:
        if self._repo.get_kv(_DAY_DATE) != _today():
            self._repo.set_kv(_DAY_START, str(equity))
            self._repo.set_kv(_DAY_DATE, _today())


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
