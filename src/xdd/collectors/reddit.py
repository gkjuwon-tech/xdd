"""Reddit collector via the public JSON endpoints (no auth needed for reads).

Pulls new posts from configured subreddits and keeps those mentioning a
watchlist ticker. Upvotes and comment counts become engagement metrics that
later feed the volume-spike / novelty features.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from xdd.collectors.base import safe_get
from xdd.domain import Signal, SignalSource

log = logging.getLogger(__name__)


class RedditCollector:
    name = "reddit"

    def __init__(self, subreddits: list[str], user_agent: str = "xdd-agent/0.1") -> None:
        self._subs = subreddits
        self._headers = {"User-Agent": user_agent}

    def collect(self, watchlist: list[str]) -> list[Signal]:
        signals: list[Signal] = []
        wl = [w.upper() for w in watchlist]
        for sub in self._subs:
            url = f"https://www.reddit.com/r/{sub}/new.json?limit=50"
            resp = safe_get(url, headers=self._headers)
            if resp is None:
                continue
            try:
                data = resp.json()
            except ValueError:
                continue
            signals.extend(self._parse(data, sub, wl))
        return signals

    def _parse(self, data: dict, sub: str, watchlist: list[str]) -> list[Signal]:
        out: list[Signal] = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            title = post.get("title", "")
            body = post.get("selftext", "") or ""
            text = f"{title} {body}".upper()
            tickers = [t for t in watchlist if f"${t}" in text or f" {t} " in f" {text} "]
            if not tickers:
                continue
            created = post.get("created_utc")
            published = (
                datetime.fromtimestamp(created, tz=timezone.utc)
                if created
                else datetime.now(timezone.utc)
            )
            out.append(
                Signal(
                    source=SignalSource.REDDIT,
                    external_id=post.get("id", title),
                    title=title,
                    body=body[:1000],
                    url=f"https://reddit.com{post.get('permalink', '')}",
                    author=post.get("author"),
                    published_at=published,
                    raw_tickers=tickers,
                    metrics={
                        "score": float(post.get("score", 0)),
                        "num_comments": float(post.get("num_comments", 0)),
                        "upvote_ratio": float(post.get("upvote_ratio", 0.0)),
                    },
                )
            )
        return out
