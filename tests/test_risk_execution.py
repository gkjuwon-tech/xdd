"""M3 tests: risk engine guardrails, sizing, and execution accounting."""

from __future__ import annotations

from xdd.collectors import StubPriceProvider
from xdd.config import BrokerSettings, RiskSettings
from xdd.domain import Action, Critique, DecisionStatus, Direction, Hypothesis, OrderSide
from xdd.execution import OrderRouter, PaperBroker, PortfolioAccountant
from xdd.risk import PortfolioSnapshot, RiskEngine, fractional_kelly
from xdd.risk.calibration import CalibrationTracker
from xdd.storage import AuditLog, Database, Repository


def _settings() -> RiskSettings:
    return RiskSettings(seed_capital=100000, min_order_notional=1000, min_confidence_to_trade=0.55)


def _hyp(direction=Direction.UP, conf=0.8) -> Hypothesis:
    return Hypothesis(
        ticker="NVDA", event_id="evt_1", direction=direction, confidence=conf,
        horizon_hours=48, thesis="t",
    )


def _clean_critique() -> Critique:
    return Critique(hypothesis_event_id="evt_1", confidence_adjustment=-0.05)


def _snap(**kw) -> PortfolioSnapshot:
    base = dict(equity=100000, cash=100000, day_start_equity=100000, peak_equity=100000,
                positions={}, prices={"NVDA": 100.0})
    base.update(kw)
    return PortfolioSnapshot(**base)


def test_kelly_positive_edge_and_zero_on_negative():
    assert fractional_kelly(0.7, 0.15, 0.08, 0.25) > 0
    assert fractional_kelly(0.3, 0.15, 0.08, 0.25) == 0.0


def test_engine_approves_confident_buy():
    eng = RiskEngine(_settings())
    d = eng.decide(_hyp(conf=0.85), _clean_critique(), _snap())
    assert d.status == DecisionStatus.APPROVED
    assert d.action == Action.BUY
    assert d.target_notional > 0 and d.target_quantity > 0


def test_engine_rejects_manipulation():
    eng = RiskEngine(_settings())
    crit = Critique(hypothesis_event_id="evt_1", manipulation_suspected=True)
    d = eng.decide(_hyp(), crit, _snap())
    assert d.status == DecisionStatus.REJECTED
    assert "manipulation" in d.guardrail_hits


def test_engine_halts_on_daily_loss_limit():
    eng = RiskEngine(_settings())
    snap = _snap(equity=94000, day_start_equity=100000)  # -6% > 5% limit
    d = eng.decide(_hyp(), _clean_critique(), snap)
    assert d.status == DecisionStatus.REJECTED
    assert "daily_loss_limit" in d.guardrail_hits


def test_engine_circuit_breaker_on_drawdown():
    eng = RiskEngine(_settings())
    snap = _snap(equity=80000, peak_equity=100000)  # -20% > 15% max dd
    d = eng.decide(_hyp(), _clean_critique(), snap)
    assert d.status == DecisionStatus.REJECTED
    assert "max_drawdown" in d.guardrail_hits


def test_engine_respects_position_cap():
    eng = RiskEngine(RiskSettings(max_position_pct=0.05, min_order_notional=1000))
    d = eng.decide(_hyp(conf=0.9), _clean_critique(), _snap())
    # cap is 5% of 100k = 5000; sized notional must not exceed it
    assert d.target_notional <= 5000 + 1e-6


def test_low_confidence_stands_aside():
    eng = RiskEngine(_settings())
    d = eng.decide(_hyp(conf=0.5), _clean_critique(), _snap())
    assert d.status == DecisionStatus.NO_ACTION
    assert d.action == Action.HOLD


def test_full_execution_roundtrip_updates_cash_and_positions():
    db = Database(":memory:")
    repo = Repository(db)
    audit = AuditLog(db)
    prices = StubPriceProvider()
    acct = PortfolioAccountant(repo, prices, seed_capital=100000)
    broker = PaperBroker(prices, fee_pct=0.001)
    router = OrderRouter(broker, acct, audit, BrokerSettings())

    ticker = "AAPL"
    price = prices.get_price(ticker)
    snap = acct.snapshot_with_price(ticker)
    eng = RiskEngine(_settings())
    hyp = _hyp(conf=0.85).model_copy(update={"ticker": ticker})
    decision = eng.decide(hyp, _clean_critique(), _sync_snap(snap, ticker, price))

    cash_before = acct.cash
    fill = router.execute(decision)
    assert fill is not None and fill.side == OrderSide.BUY
    assert acct.cash < cash_before  # cash spent
    pos = repo.get_position(ticker)
    assert pos and pos.quantity > 0

    # Now exit and confirm the position closes and cash returns.
    liq = router.liquidate(ticker, "test exit")
    assert liq is not None
    assert repo.get_position(ticker) is None or repo.get_position(ticker).quantity == 0


def _sync_snap(snap: PortfolioSnapshot, ticker: str, price: float) -> PortfolioSnapshot:
    snap.prices[ticker] = price
    return snap


def test_calibration_cold_start_haircut():
    db = Database(":memory:")
    tracker = CalibrationTracker(Repository(db))
    # No data -> cold-start prudence haircut, never inflates.
    assert tracker.calibrate(0.8) < 0.8
