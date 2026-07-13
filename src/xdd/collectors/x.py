"""X (Twitter) collector — adapter interface, live only when a token is set.

Per the project decision, X is wired as an adapter now and activated later:
without a bearer token it returns no signals (never crashes). With a token it
queries the recent-search API for cashtag mentions of watchlist tickers.
"""

from __future__ import annotations

import logging

import httpx

from xdd.domain import Signal, SignalSource

log = logging.getLogger(__name__)


class XCollector:
    name = "x"

    def __init__(self, bearer_token: str = "") -> None:
        self._token = bearer_token

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def collect(self, watchlist: list[str]) -> list[Signal]:
        if not self.enabled:
            return []
        signals: list[Signal] = []
        headers = {"Authorization": f"Bearer {self._token}"}
        for ticker in watchlist:
            query = f"%24{ticker} -is:retweet lang:en"
            url = (
                "https://api.twitter.com/2/tweets/search/recent"
                f"?query={query}&max_results=25"
                "&tweet.fields=created_at,public_metrics,author_id"
            )
            try:
                resp = httpx.get(url, headers=headers, timeout=20.0)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                log.warning("X fetch failed for %s: %s", ticker, exc)
                continue
            for tw in data.get("data", []):
                metrics = tw.get("public_metrics", {})
                signals.append(
                    Signal(
                        source=SignalSource.X,
                        external_id=tw.get("id", ""),
                        title=tw.get("text", "")[:120],
                        body=tw.get("text", ""),
                        author=tw.get("author_id"),
                        raw_tickers=[ticker],
                        metrics={
                            "likes": float(metrics.get("like_count", 0)),
                            "retweets": float(metrics.get("retweet_count", 0)),
                        },
                    )
                )
        return signals
