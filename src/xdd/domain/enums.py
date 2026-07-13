"""Enumerations shared across the domain."""

from __future__ import annotations

from enum import Enum


class SignalSource(str, Enum):
    """Where a raw signal originated."""

    NEWS = "news"
    REDDIT = "reddit"
    X = "x"
    PRICE = "price"


class AssetClass(str, Enum):
    US_EQUITY = "us_equity"
    CRYPTO = "crypto"


class Direction(str, Enum):
    """Predicted price direction of a hypothesis."""

    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class Action(str, Enum):
    """What the agent decided to do about a hypothesis."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    CANCELED = "canceled"


class DecisionStatus(str, Enum):
    """Outcome of the deterministic risk engine's review."""

    APPROVED = "approved"
    REJECTED = "rejected"
    NO_ACTION = "no_action"
