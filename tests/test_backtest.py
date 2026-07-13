"""M5 tests: backtest harness produces coherent metrics with no look-ahead."""

from __future__ import annotations

from xdd.backtest import compute_metrics, run_backtest
from xdd.backtest.engine import HistoricalPriceProvider


def test_metrics_basic():
    curve = [100, 102, 101, 105, 110]
    bench = [100, 101, 102, 103, 104]
    m = compute_metrics(curve, bench, trade_results=[True, False, True])
    assert m["total_return"] > 0
    assert "sharpe" in m and "max_drawdown" in m
    assert m["win_rate"] == round(2 / 3, 4)
    assert m["benchmark_return"] == round(0.04, 4)


def test_historical_provider_no_lookahead():
    series = {"X": [1, 2, 3, 4, 5]}
    vols = {"X": [10, 10, 10, 10, 10]}
    p = HistoricalPriceProvider(series, vols)
    p.cursor = 2
    assert p.get_price("X") == 3
    hist = p.get_history("X", 10)
    assert hist == [1, 2, 3]  # never sees the future (4, 5)


def test_run_backtest_produces_metrics():
    m = run_backtest(days=60, tickers=["AAPL", "TSLA", "NVDA"], seed_capital=100000)
    assert m["final_equity"] > 0
    assert "sharpe" in m
    assert "benchmark_return" in m
    assert "max_drawdown" in m
    assert 0.0 <= m["max_drawdown"] <= 1.0
