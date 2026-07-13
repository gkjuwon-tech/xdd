"""Point-in-time backtest harness.

Replays daily bars one day at a time. At each step the agent sees only data up
to that day (no look-ahead), forms an event (quantitative market features plus a
synthetic momentum-derived narrative sentiment), runs the full
Analyst → Skeptic → Risk → Execute pipeline, then applies stop/take exits and
marks the portfolio to market. Fees and slippage are charged via the paper
broker so the tiny-seed economics are honest.

The synthetic series is deterministic, so backtests are reproducible. Swap in a
real historical bar source by replacing ``_generate_series``.
"""

from __future__ import annotations

import hashlib

from xdd.agents import Analyst, Reviewer, Skeptic, StubLLMClient
from xdd.backtest.metrics import compute_metrics
from xdd.collectors.price import MarketDataCollector, compute_features
from xdd.config import RiskSettings
from xdd.domain import Event, SignalSource
from xdd.execution import OrderRouter, PaperBroker, PortfolioAccountant
from xdd.memory import MemoryStore
from xdd.observability import KillSwitch
from xdd.orchestrator.monitor import PositionMonitor
from xdd.risk import CalibrationTracker, RiskEngine
from xdd.storage import AuditLog, Database, Repository


class HistoricalPriceProvider:
    """Exposes a price series only up to the current simulation cursor."""

    def __init__(self, series: dict[str, list[float]], volumes: dict[str, list[float]]) -> None:
        self._series = series
        self._volumes = volumes
        self.cursor = 0  # index of "today" (inclusive)

    def get_price(self, ticker: str) -> float | None:
        s = self._series.get(ticker)
        if not s or self.cursor < 0:
            return None
        return s[min(self.cursor, len(s) - 1)]

    def get_history(self, ticker: str, days: int = 30) -> list[float]:
        s = self._series.get(ticker, [])
        end = self.cursor + 1
        return s[max(0, end - days) : end]

    def get_volumes(self, ticker: str, days: int = 30) -> list[float]:
        v = self._volumes.get(ticker, [])
        end = self.cursor + 1
        return v[max(0, end - days) : end]


def run_backtest(
    days: int = 120,
    tickers: list[str] | None = None,
    seed_capital: float = 100000.0,
    warmup: int = 25,
) -> dict:
    tickers = tickers or ["AAPL", "TSLA", "NVDA", "MSFT", "AMD"]
    total_days = days + warmup
    series, volumes = _generate_series(tickers, total_days)
    provider = HistoricalPriceProvider(series, volumes)

    db = Database(":memory:")
    repo = Repository(db)
    audit = AuditLog(db)
    accountant = PortfolioAccountant(repo, provider, seed_capital)
    broker = PaperBroker(provider, fee_pct=0.001)
    settings = RiskSettings(seed_capital=seed_capital, min_order_notional=500,
                            min_confidence_to_trade=0.55)
    calibration = CalibrationTracker(repo, min_samples=10)
    engine = RiskEngine(settings, calibration)
    from xdd.config import BrokerSettings

    router = OrderRouter(broker, accountant, audit, BrokerSettings())
    memory = MemoryStore(repo)
    analyst = Analyst(StubLLMClient(), memory)
    skeptic = Skeptic(StubLLMClient())
    reviewer = Reviewer(StubLLMClient())
    market = MarketDataCollector(provider)
    kill = KillSwitch(repo)
    monitor = PositionMonitor(
        repo, accountant, router, reviewer, calibration, memory, market, kill, audit
    )

    equity_curve: list[float] = []
    benchmark_curve: list[float] = []
    trade_results: list[bool] = []

    bench_start_prices = {t: series[t][warmup] for t in tickers}

    for day in range(warmup, total_days):
        provider.cursor = day

        # Exits first (stop / take), collecting realized results.
        for ex in monitor.run():
            trade_results.append(ex["realized_pct"] > 0)

        # Form one event per ticker and run the decision pipeline.
        for ticker in tickers:
            event = _synthetic_event(ticker, provider)
            if event is None:
                continue
            hyp = analyst.analyze(event)
            crit = skeptic.critique(event, hyp)
            snap = accountant.snapshot_with_price(ticker)
            decision = engine.decide(hyp, crit, snap)
            if decision.is_actionable:
                fill = router.execute(decision)
                if fill is not None and decision.action.value == "buy":
                    monitor.record_open_hypothesis(hyp)

        equity_curve.append(accountant.equity())
        benchmark_curve.append(_benchmark_value(series, volumes, tickers, bench_start_prices,
                                                day, seed_capital))

    metrics = compute_metrics(equity_curve, benchmark_curve, trade_results)
    metrics["reliability"] = calibration.reliability()
    metrics["days"] = days
    metrics["tickers"] = tickers
    db.close()
    return metrics


def _synthetic_event(ticker: str, provider: HistoricalPriceProvider) -> Event | None:
    closes = provider.get_history(ticker, 30)
    vols = provider.get_volumes(ticker, 30)
    feats = compute_features(closes, vols)
    if not feats:
        return None
    # Synthetic narrative sentiment from *past* momentum only (no look-ahead),
    # with deterministic per-day noise so the stub agent has something to read.
    momentum = feats.get("return_5d", 0.0)
    noise = (_hash_unit(f"{ticker}:{provider.cursor}") - 0.5) * 0.6
    sentiment = max(-1.0, min(1.0, momentum * 8 + noise))
    return Event(
        ticker=ticker,
        signals=[],
        sentiment=round(sentiment, 3),
        signal_count=1,
        novelty=0.8,
        sources=[SignalSource.PRICE],
        market=feats,
    )


def _benchmark_value(series, volumes, tickers, start_prices, day, seed_capital) -> float:
    """Equal-weight buy-and-hold of the watchlist."""
    per = seed_capital / len(tickers)
    total = 0.0
    for t in tickers:
        shares = per / start_prices[t]
        total += shares * series[t][day]
    return total


def _generate_series(tickers: list[str], n: int) -> tuple[dict, dict]:
    series: dict[str, list[float]] = {}
    volumes: dict[str, list[float]] = {}
    for t in tickers:
        seed = int(hashlib.sha1(t.encode()).hexdigest(), 16) % (2**31)
        state = seed or 1
        price = 50 + (seed % 200)
        closes, vols = [], []
        for _ in range(n):
            state = (state * 1103515245 + 12345) % (2**31)
            r = state / (2**31)
            drift = (r - 0.48) * 0.05  # slight upward bias, ±2.5%
            price = max(1.0, price * (1 + drift))
            closes.append(round(price, 2))
            state = (state * 1103515245 + 12345) % (2**31)
            vols.append(round(1_000_000 * (0.5 + state / (2**31)), 0))
        series[t] = closes
        volumes[t] = vols
    return series, volumes


def _hash_unit(s: str) -> float:
    return (int(hashlib.sha1(s.encode()).hexdigest(), 16) % 10000) / 10000.0
