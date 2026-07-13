"""OBSERVE stage: collectors that turn the outside world into :class:`Signal`s."""

from xdd.collectors.base import Collector
from xdd.collectors.news import NewsCollector
from xdd.collectors.price import (
    AlpacaPriceProvider,
    MarketDataCollector,
    PriceProvider,
    StubPriceProvider,
    compute_features,
)
from xdd.collectors.reddit import RedditCollector
from xdd.collectors.x import XCollector

__all__ = [
    "Collector",
    "NewsCollector",
    "PriceProvider",
    "StubPriceProvider",
    "AlpacaPriceProvider",
    "MarketDataCollector",
    "compute_features",
    "RedditCollector",
    "XCollector",
]
