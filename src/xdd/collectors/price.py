"""Price providers and the quantitative MarketDataCollector.

The agent must synthesize *market* data, not just headlines. This module
supplies price history and derives technical features (returns, RSI,
annualized volatility, volume z-score, trend) for every watchlist ticker, so
the Analyst always has hard numbers alongside the narrative — and so tickers
with no news still get a market snapshot.

``PriceProvider`` is an interface; ``StubPriceProvider`` generates a
deterministic pseudo-random walk (seeded per ticker/day) so the whole system
runs offline for tests and dry runs. ``AlpacaPriceProvider`` fetches real
bars when Alpaca credentials are configured.
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime, timezone
from typing import Protocol

from xdd.collectors.base import safe_get
from xdd.domain import Signal, SignalSource

log = logging.getLogger(__name__)


class PriceProvider(Protocol):
    def get_price(self, ticker: str) -> float | None:
        ...

    def get_history(self, ticker: str, days: int = 30) -> list[float]:
        """Return up to ``days`` daily closes, oldest first."""
        ...

    def get_volumes(self, ticker: str, days: int = 30) -> list[float]:
        ...


class StubPriceProvider:
    """Deterministic synthetic prices for offline development and tests.

    Prices follow a seeded geometric random walk so the same ticker yields the
    same series within a run, letting tests assert on derived features.
    """

    def __init__(self, base: float = 100.0) -> None:
        self._base = base

    def _series(self, ticker: str, days: int) -> tuple[list[float], list[float]]:
        seed = int(hashlib.sha1(ticker.encode()).hexdigest(), 16)
        rng = _Lcg(seed)
        price = self._base * (0.5 + (seed % 1000) / 1000.0)
        closes, vols = [], []
        for _ in range(days):
            drift = (rng.next() - 0.5) * 0.04  # ±2% daily
            price = max(1.0, price * (1 + drift))
            closes.append(round(price, 2))
            vols.append(round(1_000_000 * (0.5 + rng.next()), 0))
        return closes, vols

    def get_price(self, ticker: str) -> float | None:
        closes, _ = self._series(ticker, 30)
        return closes[-1]

    def get_history(self, ticker: str, days: int = 30) -> list[float]:
        closes, _ = self._series(ticker, days)
        return closes

    def get_volumes(self, ticker: str, days: int = 30) -> list[float]:
        _, vols = self._series(ticker, days)
        return vols


class _Lcg:
    """Tiny deterministic linear-congruential generator (no numpy dependency)."""

    def __init__(self, seed: int) -> None:
        self._state = seed % (2**31 - 1) or 1

    def next(self) -> float:
        self._state = (self._state * 1103515245 + 12345) % (2**31)
        return self._state / (2**31)


class AlpacaPriceProvider:
    """Fetches daily bars from Alpaca's market-data API."""

    def __init__(self, key_id: str, secret_key: str) -> None:
        self._headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._base = "https://data.alpaca.markets/v2"

    def _bars(self, ticker: str, days: int) -> list[dict]:
        url = f"{self._base}/stocks/{ticker}/bars?timeframe=1Day&limit={days}"
        resp = safe_get(url, headers=self._headers)
        if resp is None:
            return []
        try:
            return resp.json().get("bars", []) or []
        except ValueError:
            return []

    def get_history(self, ticker: str, days: int = 30) -> list[float]:
        return [b["c"] for b in self._bars(ticker, days)]

    def get_volumes(self, ticker: str, days: int = 30) -> list[float]:
        return [float(b.get("v", 0)) for b in self._bars(ticker, days)]

    def get_price(self, ticker: str) -> float | None:
        hist = self.get_history(ticker, 1)
        return hist[-1] if hist else None


# --------------------------------------------------------------------- features


def compute_features(closes: list[float], volumes: list[float]) -> dict[str, float]:
    """Derive technical features from a price/volume series."""
    if len(closes) < 2:
        return {}
    price = closes[-1]
    ret_1d = _pct_change(closes, 1)
    ret_5d = _pct_change(closes, 5)
    ret_20d = _pct_change(closes, 20)
    rsi = _rsi(closes, 14)
    vol = _annualized_vol(closes)
    sma_short = _sma(closes, 5)
    sma_long = _sma(closes, 20)
    trend = 1.0 if sma_short >= sma_long else -1.0
    volume_z = _zscore(volumes)
    return {
        "price": round(price, 4),
        "return_1d": round(ret_1d, 4),
        "return_5d": round(ret_5d, 4),
        "return_20d": round(ret_20d, 4),
        "rsi": round(rsi, 1),
        "volatility": round(vol, 4),
        "sma_short": round(sma_short, 4),
        "sma_long": round(sma_long, 4),
        "trend": trend,
        "volume_z": round(volume_z, 2),
    }


def _pct_change(series: list[float], lookback: int) -> float:
    if len(series) <= lookback or series[-1 - lookback] == 0:
        return 0.0
    return (series[-1] - series[-1 - lookback]) / series[-1 - lookback]


def _sma(series: list[float], window: int) -> float:
    w = series[-window:]
    return sum(w) / len(w) if w else 0.0


def _rsi(series: list[float], period: int = 14) -> float:
    if len(series) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        delta = series[i] - series[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - (100 / (1 + rs))


def _annualized_vol(series: list[float]) -> float:
    rets = [
        (series[i] - series[i - 1]) / series[i - 1]
        for i in range(1, len(series))
        if series[i - 1] != 0
    ]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def _zscore(series: list[float]) -> float:
    if len(series) < 2:
        return 0.0
    mean = sum(series) / len(series)
    var = sum((x - mean) ** 2 for x in series) / (len(series) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (series[-1] - mean) / std


class MarketDataCollector:
    """Emits one quantitative PRICE signal per watchlist ticker each poll."""

    name = "market"

    def __init__(self, provider: PriceProvider) -> None:
        self._provider = provider

    def collect(self, watchlist: list[str]) -> list[Signal]:
        out: list[Signal] = []
        for ticker in watchlist:
            closes = self._provider.get_history(ticker, 30)
            if not closes:
                continue
            volumes = self._provider.get_volumes(ticker, 30)
            feats = compute_features(closes, volumes)
            if not feats:
                continue
            now = datetime.now(timezone.utc)
            out.append(
                Signal(
                    source=SignalSource.PRICE,
                    external_id=f"{ticker}:{now.strftime('%Y%m%d%H')}",
                    title=f"{ticker} market snapshot",
                    body=(
                        f"price={feats['price']} ret_1d={feats['return_1d']:+.2%} "
                        f"rsi={feats['rsi']} vol_z={feats['volume_z']:+.1f}"
                    ),
                    published_at=now,
                    raw_tickers=[ticker],
                    metrics=feats,
                )
            )
        return out

    def snapshot(self, ticker: str) -> dict[str, float]:
        closes = self._provider.get_history(ticker, 30)
        volumes = self._provider.get_volumes(ticker, 30)
        return compute_features(closes, volumes)
