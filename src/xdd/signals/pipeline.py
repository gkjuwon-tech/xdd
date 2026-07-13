"""Signal pipeline: raw signals -> filtered, deduped, ticker-scoped Events.

Steps:
  1. Deduplicate against previously seen signals (persisted).
  2. Drop manipulation / spam.
  3. Score sentiment per signal.
  4. Group by ticker within the configured time window.
  5. Merge in quantitative market features (from PRICE signals).
  6. Compute an aggregate sentiment and a novelty score, then emit Events
     ranked by how much fresh, high-conviction signal they carry.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from xdd.domain import Event, Signal, SignalSource
from xdd.signals.sentiment import score_sentiment
from xdd.signals.spam_filter import ManipulationFilter
from xdd.storage import AuditLog, Repository

log = logging.getLogger(__name__)


class SignalPipeline:
    def __init__(
        self,
        repo: Repository,
        audit: AuditLog,
        *,
        window_hours: float = 12.0,
        manipulation_filter: ManipulationFilter | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._window = timedelta(hours=window_hours)
        self._filter = manipulation_filter or ManipulationFilter()

    def process(self, signals: list[Signal]) -> list[Event]:
        fresh = self._dedup(signals)
        kept, dropped = self._filter.filter(fresh)
        for sig, reason in dropped:
            self._audit.record(
                "observe", "signal_dropped", {"signal": sig.model_dump(mode="json"), "reason": reason},
                ticker=sig.raw_tickers[0] if sig.raw_tickers else None,
            )
        events = self._to_events(kept)
        for ev in events:
            self._audit.record("observe", "event_formed", ev, event_id=ev.event_id, ticker=ev.ticker)
        # Highest-conviction, freshest events first.
        events.sort(key=lambda e: (abs(e.sentiment) * e.novelty, e.signal_count), reverse=True)
        return events

    # ------------------------------------------------------------------ dedup
    def _dedup(self, signals: list[Signal]) -> list[Signal]:
        fresh: list[Signal] = []
        for s in signals:
            if self._repo.is_seen(s.dedup_key):
                continue
            self._repo.mark_seen(s.dedup_key)
            fresh.append(s)
        return fresh

    # ---------------------------------------------------------------- grouping
    def _to_events(self, signals: list[Signal]) -> list[Event]:
        now = datetime.now(timezone.utc)
        cutoff = now - self._window

        # Split market snapshots (quantitative) from narrative signals.
        market_by_ticker: dict[str, dict[str, float]] = {}
        narrative: dict[str, list[Signal]] = {}
        for s in signals:
            if s.source == SignalSource.PRICE:
                for t in s.raw_tickers:
                    market_by_ticker[t] = dict(s.metrics)
                continue
            if s.published_at < cutoff:
                continue
            for t in s.raw_tickers or _guess_tickers(s):
                narrative.setdefault(t, []).append(s)

        events: list[Event] = []
        # A ticker with pure market movement (no news) is still worth an event.
        tickers = set(narrative) | set(market_by_ticker)
        for ticker in tickers:
            group = narrative.get(ticker, [])
            market = market_by_ticker.get(ticker, {})
            events.append(self._build_event(ticker, group, market, now))
        return events

    def _build_event(
        self, ticker: str, group: list[Signal], market: dict[str, float], now: datetime
    ) -> Event:
        sentiments = []
        weights = []
        sources: set[SignalSource] = set()
        for s in group:
            sent = score_sentiment(s.text)
            weight = 1.0 + _engagement_weight(s)
            sentiments.append(sent)
            weights.append(weight)
            sources.add(s.source)

        agg = _weighted_mean(sentiments, weights) if sentiments else 0.0
        novelty = _novelty(group, market, agg, now)

        if market:
            sources.add(SignalSource.PRICE)

        return Event(
            ticker=ticker,
            signals=sorted(group, key=lambda s: s.published_at, reverse=True),
            sentiment=round(agg, 4),
            signal_count=len(group),
            novelty=round(novelty, 4),
            sources=sorted(sources, key=lambda s: s.value),
            market=market,
        )


def _engagement_weight(signal: Signal) -> float:
    if signal.source == SignalSource.REDDIT:
        return min(2.0, signal.metrics.get("score", 0.0) / 500.0)
    if signal.source == SignalSource.X:
        engagement = signal.metrics.get("likes", 0.0) + signal.metrics.get("retweets", 0.0)
        return min(2.0, engagement / 1000.0)
    return 0.5  # news carries steady baseline weight


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    if total == 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total


def _novelty(
    signals: list[Signal], market: dict[str, float], sentiment: float, now: datetime
) -> float:
    """Estimate how much of the signal is *fresh* vs already priced in."""
    if not signals and not market:
        return 0.0
    # Recency: newer signals => more novel.
    if signals:
        ages = [(now - s.published_at).total_seconds() / 3600.0 for s in signals]
        recency = max(0.0, 1.0 - min(ages) / 24.0)
    else:
        recency = 0.3  # pure market move, mild novelty

    # Priced-in penalty: if the day's move already agrees strongly with the
    # sentiment direction, the news is likely reflected in price.
    ret_1d = market.get("return_1d", 0.0)
    priced_in = 0.0
    if sentiment != 0 and ret_1d != 0 and (sentiment > 0) == (ret_1d > 0):
        priced_in = min(0.5, abs(ret_1d) * 10)
    return max(0.0, min(1.0, recency - priced_in))


def _guess_tickers(signal: Signal) -> list[str]:
    return signal.raw_tickers
