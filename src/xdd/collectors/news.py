"""News collector: parses financial RSS feeds into signals.

Uses the stdlib XML parser so no feed-parsing dependency is required. Only
items whose title/summary mention a watchlist ticker (or company alias) are
kept, to bound volume.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from xdd.collectors.base import safe_get
from xdd.domain import Signal, SignalSource

log = logging.getLogger(__name__)


class NewsCollector:
    name = "news"

    def __init__(self, rss_urls: list[str]) -> None:
        self._urls = rss_urls

    def collect(self, watchlist: list[str]) -> list[Signal]:
        signals: list[Signal] = []
        wl = [w.upper() for w in watchlist]
        for url in self._urls:
            resp = safe_get(url)
            if resp is None:
                continue
            signals.extend(self._parse(resp.text, url, wl))
        return signals

    def _parse(self, xml_text: str, feed_url: str, watchlist: list[str]) -> list[Signal]:
        out: list[Signal] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            log.warning("failed to parse RSS %s: %s", feed_url, exc)
            return out
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            body = (item.findtext("description") or "").strip()
            link = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link or title).strip()
            pub = item.findtext("pubDate")
            published = _parse_date(pub)
            text = f"{title} {body}".upper()
            tickers = [t for t in watchlist if _mentions(text, t)]
            if not tickers:
                continue
            out.append(
                Signal(
                    source=SignalSource.NEWS,
                    external_id=guid,
                    title=title,
                    body=body[:1000],
                    url=link or None,
                    published_at=published,
                    raw_tickers=tickers,
                )
            )
        return out


def _mentions(text_upper: str, ticker: str) -> bool:
    # word-ish boundary check to avoid substring false positives
    return f" {ticker} " in f" {text_upper} " or f"${ticker}" in text_upper


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
