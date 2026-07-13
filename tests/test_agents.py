"""M2 tests: Analyst, Skeptic, Reviewer with the offline stub LLM."""

from __future__ import annotations

from xdd.agents import Analyst, Reviewer, Skeptic, StubLLMClient
from xdd.agents.llm import parse_json
from xdd.domain import Direction, Event, Signal, SignalSource
from xdd.memory import MemoryStore
from xdd.storage import Database, Repository


def _bullish_event() -> Event:
    return Event(
        ticker="NVDA",
        signals=[
            Signal(source=SignalSource.NEWS, external_id="1", title="NVDA beats, rallies",
                   raw_tickers=["NVDA"])
        ],
        sentiment=0.6,
        signal_count=1,
        novelty=0.9,
        sources=[SignalSource.NEWS, SignalSource.PRICE],
        market={"price": 120.0, "return_1d": 0.01, "rsi": 55.0, "trend": 1.0},
    )


def test_parse_json_tolerates_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('noise {"a": 2} trailing') == {"a": 2}


def test_analyst_produces_hypothesis():
    analyst = Analyst(StubLLMClient())
    hyp = analyst.analyze(_bullish_event())
    assert hyp.ticker == "NVDA"
    assert hyp.direction == Direction.UP
    assert 0.0 <= hyp.confidence <= 1.0


def test_skeptic_only_lowers_confidence():
    skeptic = Skeptic(StubLLMClient())
    event = _bullish_event()
    analyst = Analyst(StubLLMClient())
    hyp = analyst.analyze(event)
    crit = skeptic.critique(event, hyp)
    assert crit.confidence_adjustment <= 0.0


def test_reviewer_extracts_lesson_and_memory_roundtrip():
    db = Database(":memory:")
    repo = Repository(db)
    memory = MemoryStore(repo)
    analyst = Analyst(StubLLMClient(), memory)
    reviewer = Reviewer(StubLLMClient())

    event = _bullish_event()
    hyp = analyst.analyze(event)
    lesson = reviewer.review(hyp, realized_pnl_pct=0.08, market_context=event.market)
    assert lesson.was_correct is True
    memory.add(lesson)

    # A later analysis of a similar NVDA event should retrieve the lesson.
    retrieved = memory.retrieve(event.summary(), ticker="NVDA", k=3)
    assert any(les.ticker == "NVDA" for les in retrieved)
