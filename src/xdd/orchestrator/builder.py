"""Factory that assembles the whole trading system from settings.

This is the single wiring point: pick collectors, broker, price provider, and
LLM based on configuration, then construct the cognitive loop. Everything
downstream depends only on the assembled objects, not on config.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from xdd.agents import Analyst, Reviewer, Skeptic, build_llm
from xdd.collectors import (
    MarketDataCollector,
    NewsCollector,
    RedditCollector,
    XCollector,
)
from xdd.collectors.price import AlpacaPriceProvider, PriceProvider, StubPriceProvider
from xdd.config import AppSettings, get_settings
from xdd.execution import OrderRouter, PaperBroker, PortfolioAccountant
from xdd.execution.alpaca_broker import AlpacaBroker
from xdd.execution.router import ApprovalCallback
from xdd.memory import MemoryStore
from xdd.observability import KillSwitch
from xdd.orchestrator.loop import CognitiveLoop
from xdd.orchestrator.monitor import PositionMonitor
from xdd.risk import CalibrationTracker, RiskEngine
from xdd.signals import SignalPipeline
from xdd.storage import AuditLog, Database, Repository

log = logging.getLogger(__name__)


@dataclass
class TradingSystem:
    """Bundle of every wired component, with convenient accessors."""

    settings: AppSettings
    db: Database
    repo: Repository
    audit: AuditLog
    accountant: PortfolioAccountant
    kill_switch: KillSwitch
    loop: CognitiveLoop
    market: MarketDataCollector

    def run_cycle(self):
        return self.loop.run_cycle()


def _price_provider(settings: AppSettings) -> PriceProvider:
    b = settings.broker
    if b.backend == "alpaca" and b.alpaca_key_id and b.alpaca_secret_key:
        return AlpacaPriceProvider(b.alpaca_key_id, b.alpaca_secret_key)
    return StubPriceProvider()


def _broker(settings: AppSettings, prices: PriceProvider):
    b = settings.broker
    if b.backend == "alpaca" and b.alpaca_key_id and b.alpaca_secret_key:
        return AlpacaBroker(b.alpaca_key_id, b.alpaca_secret_key, b.alpaca_base_url)
    return PaperBroker(prices, fee_pct=settings.risk.fee_pct)


def build_system(
    settings: AppSettings | None = None,
    *,
    approval_callback: ApprovalCallback | None = None,
) -> TradingSystem:
    settings = settings or get_settings()

    db = Database(settings.db_path)
    repo = Repository(db)
    audit = AuditLog(db)

    prices = _price_provider(settings)
    market = MarketDataCollector(prices)

    collectors = [
        NewsCollector(settings.data.news_rss_urls),
        RedditCollector(settings.data.reddit_subreddits, settings.data.reddit_user_agent),
        XCollector(settings.data.x_bearer_token),
        market,
    ]

    pipeline = SignalPipeline(repo, audit, window_hours=settings.data.signal_window_hours)

    llm = build_llm(settings.llm)
    memory = MemoryStore(repo)
    analyst = Analyst(llm, memory)
    skeptic = Skeptic(llm)
    reviewer = Reviewer(llm)

    calibration = CalibrationTracker(repo)
    risk_engine = RiskEngine(settings.risk, calibration)

    accountant = PortfolioAccountant(repo, prices, settings.risk.seed_capital)
    broker = _broker(settings, prices)
    router = OrderRouter(broker, accountant, audit, settings.broker, approval_callback)

    kill_switch = KillSwitch(repo)
    monitor = PositionMonitor(
        repo, accountant, router, reviewer, calibration, memory, market, kill_switch, audit
    )

    loop = CognitiveLoop(
        settings, collectors, pipeline, analyst, skeptic, risk_engine,
        router, accountant, monitor, kill_switch, audit, market,
    )

    log.info(
        "system built: broker=%s llm=%s watchlist=%d",
        broker.name, settings.llm.model if not settings.llm.use_stub else "stub",
        len(settings.data.watchlist),
    )
    return TradingSystem(
        settings=settings, db=db, repo=repo, audit=audit, accountant=accountant,
        kill_switch=kill_switch, loop=loop, market=market,
    )
