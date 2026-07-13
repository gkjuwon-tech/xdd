"""Position sizing via fractional Kelly.

Kelly maximizes long-run growth but is famously aggressive; on a tiny seed we
use a fraction (default quarter-Kelly) and hard caps on top. The payoff ratio
is approximated from the take-profit / stop-loss the risk engine will attach.
"""

from __future__ import annotations


def fractional_kelly(
    win_prob: float,
    take_profit_pct: float,
    stop_loss_pct: float,
    fraction: float = 0.25,
) -> float:
    """Return the fraction of equity to deploy, in [0, fraction].

    Kelly for a bet that wins ``b`` per unit risked with probability ``p``:
        f* = p - (1 - p) / b
    where ``b = take_profit / stop_loss``. Negative-edge bets return 0.
    """
    if take_profit_pct <= 0 or stop_loss_pct <= 0:
        return 0.0
    p = max(0.0, min(1.0, win_prob))
    b = take_profit_pct / stop_loss_pct
    kelly = p - (1 - p) / b
    if kelly <= 0:
        return 0.0
    return min(fraction, kelly * fraction)
