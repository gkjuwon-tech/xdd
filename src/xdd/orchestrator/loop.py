"""The cognitive loop: OBSERVE -> ORIENT -> DECIDE -> ACT -> REFLECT.

One ``run_cycle`` executes the full OODA+reflect loop once. The scheduler calls
it on the configured cadence (hourly batch by default). Everything the loop
does is written to the audit log so any decision is reconstructable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from xdd.agents import Analyst, Skeptic
from xdd.collectors.price import MarketDataCollector
from xdd.config import AppSettings
from xdd.domain import DecisionStatus, Event, Signal
from xdd.execution import OrderRouter, PortfolioAccountant
from xdd.observability import KillSwitch
from xdd.orchestrator.monitor import PositionMonitor
from xdd.risk import RiskEngine
from xdd.signals import SignalPipeline
from xdd.storage import AuditLog

log = logging.getLogger(__name__)


@dataclass
class CycleReport:
    signals_collected: int = 0
    events_formed: int = 0
    events_analyzed: int = 0
    decisions: list[dict] = field(default_factory=list)
    exits: list[dict] = field(default_factory=list)
    equity: float = 0.0
    halted: bool = False
    note: str = ""


class CognitiveLoop:
    def __init__(
        self,
        settings: AppSettings,
        collectors: list,
        pipeline: SignalPipeline,
        analyst: Analyst,
        skeptic: Skeptic,
        risk_engine: RiskEngine,
        router: OrderRouter,
        accountant: PortfolioAccountant,
        monitor: PositionMonitor,
        kill_switch: KillSwitch,
        audit: AuditLog,
        market: MarketDataCollector,
    ) -> None:
        self._s = settings
        self._collectors = collectors
        self._pipeline = pipeline
        self._analyst = analyst
        self._skeptic = skeptic
        self._risk = risk_engine
        self._router = router
        self._acct = accountant
        self._monitor = monitor
        self._kill = kill_switch
        self._audit = audit
        self._market = market

    def run_cycle(self) -> CycleReport:
        report = CycleReport()

        # First: exits and circuit breaker — protect capital before adding risk.
        report.exits = self._monitor.run()
        if self._check_circuit_breaker():
            report.halted = True
            report.note = "circuit breaker / kill switch engaged"
            report.equity = self._acct.equity()
            self._audit.record("orchestrator", "halted", {"reason": report.note})
            return report

        # OBSERVE
        signals = self._collect()
        report.signals_collected = len(signals)

        # Normalize into events (qualitative + quantitative)
        events = self._pipeline.process(signals)
        report.events_formed = len(events)

        # ORIENT / DECIDE / ACT for the top events this cycle
        for event in events[: self._s.max_events_per_cycle]:
            self._process_event(event, report)
            report.events_analyzed += 1

        report.equity = self._acct.equity()
        self._audit.record(
            "orchestrator", "cycle_summary",
            {
                "signals": report.signals_collected,
                "events": report.events_formed,
                "analyzed": report.events_analyzed,
                "decisions": report.decisions,
                "exits": report.exits,
                "equity": report.equity,
            },
        )
        return report

    # ------------------------------------------------------------------ stages
    def _collect(self) -> list[Signal]:
        signals: list[Signal] = []
        watchlist = self._s.data.watchlist
        for collector in self._collectors:
            try:
                signals.extend(collector.collect(watchlist))
            except Exception as exc:  # noqa: BLE001
                log.warning("collector %s failed: %s", getattr(collector, "name", "?"), exc)
        return signals[: self._s.data.max_signals_per_poll]

    def _process_event(self, event: Event, report: CycleReport) -> None:
        hypothesis = self._analyst.analyze(event)
        self._audit.record("orient", "hypothesis", hypothesis, event_id=event.event_id, ticker=event.ticker)

        critique = self._skeptic.critique(event, hypothesis)
        self._audit.record("orient", "critique", critique, event_id=event.event_id, ticker=event.ticker)

        snapshot = self._acct.snapshot_with_price(event.ticker)
        decision = self._risk.decide(hypothesis, critique, snapshot)
        self._audit.record("decide", "decision", decision, event_id=event.event_id, ticker=event.ticker)

        entry = {
            "ticker": event.ticker,
            "action": decision.action.value,
            "status": decision.status.value,
            "confidence": decision.effective_confidence,
        }

        if decision.is_actionable:
            fill = self._router.execute(decision)
            if fill is not None:
                if decision.status == DecisionStatus.APPROVED and decision.action.value == "buy":
                    self._monitor.record_open_hypothesis(hypothesis)
                entry["filled"] = True
                entry["price"] = fill.price
            else:
                entry["filled"] = False
        report.decisions.append(entry)

    def _check_circuit_breaker(self) -> bool:
        if self._kill.engaged:
            self._liquidate_all("kill switch engaged")
            return True
        snap = self._acct.snapshot()
        if snap.drawdown_pct >= self._s.risk.max_drawdown_pct:
            self._kill.engage(f"max drawdown {snap.drawdown_pct:.1%}")
            self._liquidate_all("max drawdown circuit breaker")
            return True
        return False

    def _liquidate_all(self, reason: str) -> None:
        for ticker in list(self._acct.snapshot().positions):
            self._router.liquidate(ticker, reason)
