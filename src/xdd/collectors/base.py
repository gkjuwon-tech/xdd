"""Collector protocol and shared helpers."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from xdd.domain import Signal

log = logging.getLogger(__name__)


class Collector(Protocol):
    """Anything that can produce raw signals for the current watchlist."""

    name: str

    def collect(self, watchlist: list[str]) -> list[Signal]:
        ...


def safe_get(url: str, *, headers: dict | None = None, timeout: float = 20.0) -> httpx.Response | None:
    """GET a URL, returning ``None`` on any network/HTTP error.

    Collectors must never crash the cycle because one source is down; a
    missing source just means fewer signals this poll.
    """

    try:
        resp = httpx.get(url, headers=headers or {}, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp
    except Exception as exc:  # noqa: BLE001 - defensive by design
        log.warning("collector fetch failed for %s: %s", url, exc)
        return None
