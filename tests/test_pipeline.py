"""M1 tests: collectors → signal pipeline → events, all offline."""

from __future__ import annotations

from xdd.collectors import MarketDataCollector, StubPriceProvider, compute_features
from xdd.domain import Signal, SignalSource
from xdd.signals import SignalPipeline, score_sentiment
from xdd.signals.spam_filter import ManipulationFilter
from xdd.storage import AuditLog, Database, Repository


def _make_pipeline() -> tuple[SignalPipeline, Repository]:
    db = Database(":memory:")
    repo = Repository(db)
    audit = AuditLog(db)
    return SignalPipeline(repo, audit, window_hours=48), repo


def test_sentiment_direction():
    assert score_sentiment("Company beats earnings, stock surges to record") > 0
    assert score_sentiment("Massive plunge after fraud probe and lawsuit") < 0
    assert score_sentiment("The meeting is scheduled for Tuesday") == 0.0


def test_manipulation_filter_flags_pump():
    f = ManipulationFilter()
    pump = Signal(
        source=SignalSource.REDDIT,
        external_id="1",
        title="TSLA to the moon guaranteed 10x",
        body="load up now before it explodes",
        raw_tickers=["TSLA"],
        metrics={"score": 5},
    )
    suspicious, reason = f.is_suspicious(pump)
    assert suspicious and reason


def test_market_features_present():
    provider = StubPriceProvider()
    feats = compute_features(provider.get_history("AAPL", 30), provider.get_volumes("AAPL", 30))
    assert {"price", "rsi", "return_1d", "volatility", "trend"} <= set(feats)
    assert 0 <= feats["rsi"] <= 100


def test_pipeline_builds_events_with_market_context():
    pipeline, _ = _make_pipeline()
    market = MarketDataCollector(StubPriceProvider())
    news = Signal(
        source=SignalSource.NEWS,
        external_id="n1",
        title="NVDA beats and raises guidance, shares rally",
        body="strong demand",
        raw_tickers=["NVDA"],
    )
    signals = [news] + market.collect(["NVDA", "AAPL"])
    events = pipeline.process(signals)
    by_ticker = {e.ticker: e for e in events}
    assert "NVDA" in by_ticker
    nvda = by_ticker["NVDA"]
    assert nvda.sentiment > 0
    assert nvda.market  # quantitative context merged in
    assert "price" in nvda.market


def test_pipeline_dedups():
    pipeline, _ = _make_pipeline()
    s = Signal(source=SignalSource.NEWS, external_id="dup", title="AAPL up", raw_tickers=["AAPL"])
    first = pipeline.process([s])
    second = pipeline.process([s])
    assert any(e.ticker == "AAPL" for e in first)
    assert all(e.signal_count == 0 for e in second if e.ticker == "AAPL")
