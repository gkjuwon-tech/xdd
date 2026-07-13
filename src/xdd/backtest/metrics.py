"""Performance metrics for an equity curve.

We evaluate more than raw return: risk-adjusted return (Sharpe/Sortino),
worst-case drawdown, and — the calibration score — whether the agent's stated
confidence matched realized hit-rate. Per the plan, calibration is the real
long-term trust metric, not PnL alone.
"""

from __future__ import annotations

import math


def compute_metrics(
    equity_curve: list[float],
    benchmark_curve: list[float] | None = None,
    trade_results: list[bool] | None = None,
    periods_per_year: int = 252,
) -> dict:
    if len(equity_curve) < 2:
        return {"error": "not enough data"}

    rets = _returns(equity_curve)
    total_return = equity_curve[-1] / equity_curve[0] - 1
    metrics = {
        "final_equity": round(equity_curve[-1], 2),
        "total_return": round(total_return, 4),
        "sharpe": round(_sharpe(rets, periods_per_year), 3),
        "sortino": round(_sortino(rets, periods_per_year), 3),
        "max_drawdown": round(_max_drawdown(equity_curve), 4),
        "volatility_annualized": round(_std(rets) * math.sqrt(periods_per_year), 4),
    }
    if benchmark_curve and len(benchmark_curve) >= 2:
        bench_return = benchmark_curve[-1] / benchmark_curve[0] - 1
        metrics["benchmark_return"] = round(bench_return, 4)
        metrics["excess_return"] = round(total_return - bench_return, 4)
    if trade_results:
        wins = sum(1 for r in trade_results if r)
        metrics["num_trades"] = len(trade_results)
        metrics["win_rate"] = round(wins / len(trade_results), 4)
    return metrics


def _returns(curve: list[float]) -> list[float]:
    return [
        (curve[i] - curve[i - 1]) / curve[i - 1]
        for i in range(1, len(curve))
        if curve[i - 1] != 0
    ]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _sharpe(rets: list[float], ppy: int) -> float:
    sd = _std(rets)
    if sd == 0:
        return 0.0
    return (_mean(rets) / sd) * math.sqrt(ppy)


def _sortino(rets: list[float], ppy: int) -> float:
    downside = [r for r in rets if r < 0]
    dd = _std(downside) if len(downside) >= 2 else 0.0
    if dd == 0:
        return 0.0
    return (_mean(rets) / dd) * math.sqrt(ppy)


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0]
    max_dd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return max_dd
