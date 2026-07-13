"""Command-line interface.

    xdd run-once     run a single cognitive cycle and print the report
    xdd run          start the scheduled batch runner (N cycles/day)
    xdd dashboard    launch the web dashboard
    xdd status       print portfolio state
    xdd kill         engage the kill switch (halt + liquidate next cycle)
    xdd release      release the kill switch
    xdd backtest     replay historical/synthetic data and print metrics
"""

from __future__ import annotations

import argparse
import json
import sys

from xdd.config import get_settings
from xdd.observability import setup_logging
from xdd.orchestrator import build_system


def _cmd_run_once(args) -> int:
    system = build_system()
    report = system.run_cycle()
    print(
        json.dumps(
            {
                "signals": report.signals_collected,
                "events": report.events_formed,
                "analyzed": report.events_analyzed,
                "decisions": report.decisions,
                "exits": report.exits,
                "equity": round(report.equity, 2),
                "halted": report.halted,
            },
            indent=2,
        )
    )
    return 0


def _cmd_run(args) -> int:
    from xdd.orchestrator.scheduler import run_scheduled

    system = build_system()
    run_scheduled(system)
    return 0


def _cmd_dashboard(args) -> int:
    import uvicorn

    from xdd.observability.dashboard import create_app

    system = build_system()
    app = create_app(system)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _cmd_status(args) -> int:
    system = build_system()
    snap = system.accountant.snapshot()
    print(
        json.dumps(
            {
                "equity": round(snap.equity, 2),
                "cash": round(snap.cash, 2),
                "day_pnl_pct": round(snap.day_pnl_pct, 4),
                "drawdown_pct": round(snap.drawdown_pct, 4),
                "kill_switch": system.kill_switch.engaged,
                "positions": [
                    {
                        "ticker": t,
                        "quantity": round(p.quantity, 4),
                        "avg_price": round(p.avg_price, 2),
                        "pnl_pct": round(p.unrealized_pnl_pct(snap.prices.get(t, p.avg_price)), 4),
                    }
                    for t, p in snap.positions.items()
                ],
            },
            indent=2,
        )
    )
    return 0


def _cmd_kill(args) -> int:
    system = build_system()
    system.kill_switch.engage(args.reason)
    print("kill switch ENGAGED")
    return 0


def _cmd_release(args) -> int:
    system = build_system()
    system.kill_switch.release()
    print("kill switch released")
    return 0


def _cmd_backtest(args) -> int:
    from xdd.backtest import run_backtest

    metrics = run_backtest(days=args.days, tickers=args.tickers or None)
    print(json.dumps(metrics, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="xdd", description="autonomous trading agent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run-once").set_defaults(func=_cmd_run_once)
    sub.add_parser("run").set_defaults(func=_cmd_run)

    d = sub.add_parser("dashboard")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8000)
    d.set_defaults(func=_cmd_dashboard)

    sub.add_parser("status").set_defaults(func=_cmd_status)

    k = sub.add_parser("kill")
    k.add_argument("--reason", default="manual")
    k.set_defaults(func=_cmd_kill)

    sub.add_parser("release").set_defaults(func=_cmd_release)

    bt = sub.add_parser("backtest")
    bt.add_argument("--days", type=int, default=120)
    bt.add_argument("--tickers", nargs="*")
    bt.set_defaults(func=_cmd_backtest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
