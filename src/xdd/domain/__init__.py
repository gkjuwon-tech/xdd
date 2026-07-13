"""Core domain types for the trading agent.

These types are the vocabulary shared across every layer: collectors emit
:class:`Signal`, the signal pipeline turns them into :class:`Event`, the
Analyst produces a :class:`Hypothesis`, the Skeptic attaches a
:class:`Critique`, the risk engine emits a :class:`Decision`, and execution
records :class:`Order` / :class:`Fill` / :class:`Position`.
"""

from xdd.domain.enums import (
    Action,
    AssetClass,
    DecisionStatus,
    Direction,
    OrderSide,
    OrderStatus,
    SignalSource,
)
from xdd.domain.events import Event, Signal
from xdd.domain.hypothesis import Critique, Hypothesis
from xdd.domain.memory import Lesson
from xdd.domain.orders import Decision, Fill, Order, Position

__all__ = [
    "Action",
    "AssetClass",
    "DecisionStatus",
    "Direction",
    "OrderSide",
    "OrderStatus",
    "SignalSource",
    "Event",
    "Signal",
    "Critique",
    "Hypothesis",
    "Lesson",
    "Decision",
    "Fill",
    "Order",
    "Position",
]
