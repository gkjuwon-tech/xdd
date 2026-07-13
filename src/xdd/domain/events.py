"""Raw signals and normalized events (the OBSERVE stage output)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from xdd.domain.enums import SignalSource


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Signal(BaseModel):
    """A single raw observation from a collector.

    A signal is intentionally low-level: one news article, one Reddit post,
    one tweet, or one price tick. The signal pipeline deduplicates, filters,
    and aggregates signals into :class:`Event` objects.
    """

    source: SignalSource
    external_id: str = Field(description="Stable id from the source, used for dedup")
    title: str = ""
    body: str = ""
    url: str | None = None
    author: str | None = None
    published_at: datetime = Field(default_factory=_utcnow)
    collected_at: datetime = Field(default_factory=_utcnow)
    # Source-specific engagement metrics (upvotes, retweets, ...).
    metrics: dict[str, float] = Field(default_factory=dict)
    # Tickers explicitly tagged by the source, if any.
    raw_tickers: list[str] = Field(default_factory=list)

    @property
    def dedup_key(self) -> str:
        """Stable key used to detect duplicates across polls."""
        return f"{self.source.value}:{self.external_id}"

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()


class Event(BaseModel):
    """A normalized, ticker-scoped event derived from one or more signals.

    Events are what the Analyst reasons about. Each event bundles the signals
    that mention a particular ticker within a time window, plus derived
    features (aggregate sentiment, volume spike, dominant sources).
    """

    ticker: str
    signals: list[Signal] = Field(default_factory=list)
    sentiment: float = Field(0.0, ge=-1.0, le=1.0, description="Aggregate [-1, 1]")
    signal_count: int = 0
    novelty: float = Field(1.0, ge=0.0, le=1.0, description="1=fresh, 0=stale/priced-in")
    sources: list[SignalSource] = Field(default_factory=list)
    # Quantitative market context (price, returns, RSI, volatility, volume z-score,
    # trend). Populated by the MarketDataCollector so the Analyst reasons over both
    # qualitative narrative *and* hard market data — not headlines alone.
    market: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def event_id(self) -> str:
        keys = "|".join(sorted(s.dedup_key for s in self.signals))
        digest = hashlib.sha1(f"{self.ticker}:{keys}".encode()).hexdigest()[:12]
        return f"evt_{digest}"

    def summary(self) -> str:
        """A compact, LLM-friendly rendering of the event."""
        lines = [
            f"Ticker: {self.ticker}",
            f"Signals: {self.signal_count} from {', '.join(s.value for s in self.sources)}",
            f"Aggregate sentiment: {self.sentiment:+.2f}  novelty: {self.novelty:.2f}",
        ]
        if self.market:
            m = self.market
            lines.append(
                "Market: "
                + f"price={m.get('price', 0):.2f} "
                + f"ret_1d={m.get('return_1d', 0):+.2%} "
                + f"ret_5d={m.get('return_5d', 0):+.2%} "
                + f"rsi={m.get('rsi', 0):.0f} "
                + f"vol_ann={m.get('volatility', 0):.2%} "
                + f"vol_z={m.get('volume_z', 0):+.1f} "
                + f"trend={'up' if m.get('trend', 0) > 0 else 'down'}"
            )
        lines.append("")
        for s in self.signals[:12]:
            when = s.published_at.strftime("%Y-%m-%d %H:%M")
            lines.append(f"- [{s.source.value} {when}] {s.title}")
            if s.body:
                lines.append(f"    {s.body[:280]}")
        return "\n".join(lines)
