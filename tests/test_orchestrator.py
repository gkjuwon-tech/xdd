"""M4 tests: the full cognitive loop end-to-end, offline and hermetic."""

from __future__ import annotations

from xdd.config import (
    AppSettings,
    BrokerSettings,
    DataSettings,
    LLMSettings,
    RiskSettings,
)
from xdd.orchestrator import build_system


def _offline_settings() -> AppSettings:
    # Empty network collectors + stub LLM + in-memory db => fully hermetic.
    return AppSettings(
        db_path=":memory:",
        max_events_per_cycle=8,
        llm=LLMSettings(use_stub=True),
        data=DataSettings(
            news_rss_urls=[],
            reddit_subreddits=[],
            x_bearer_token="",
            watchlist=["AAPL", "TSLA", "NVDA", "AMD"],
        ),
        risk=RiskSettings(seed_capital=100000, min_order_notional=500, min_confidence_to_trade=0.5),
        broker=BrokerSettings(backend="paper", live_trading=False),
    )


def test_full_cycle_runs_and_records():
    system = build_system(_offline_settings())
    report = system.run_cycle()
    assert report.signals_collected >= 4  # one market snapshot per ticker
    assert report.events_formed >= 1
    assert report.equity > 0
    # Audit log captured the cycle.
    recent = system.audit.recent(50)
    kinds = {r["kind"] for r in recent}
    assert "cycle_summary" in kinds
    assert "hypothesis" in kinds
    assert "decision" in kinds


def test_kill_switch_halts_and_liquidates():
    system = build_system(_offline_settings())
    system.run_cycle()  # possibly opens positions
    system.kill_switch.engage("test")
    report = system.run_cycle()
    assert report.halted is True
    assert not system.accountant.snapshot().positions  # everything liquidated


def test_multiple_cycles_are_stable():
    system = build_system(_offline_settings())
    for _ in range(3):
        report = system.run_cycle()
        assert report.equity > 0
    # Equity should never be absurd (no runaway leverage).
    assert system.accountant.equity() > 0
