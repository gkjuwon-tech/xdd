"""Backtesting: point-in-time replay with no look-ahead, plus metrics."""

from xdd.backtest.engine import run_backtest
from xdd.backtest.metrics import compute_metrics

__all__ = ["run_backtest", "compute_metrics"]
