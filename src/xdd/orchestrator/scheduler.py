"""Scheduled-batch runner (the chosen operating mode: N cycles/day).

Uses APScheduler to fire ``run_cycle`` on the configured cadence. A lightweight
fallback loop is provided when APScheduler is unavailable.
"""

from __future__ import annotations

import logging
import time

from xdd.orchestrator.builder import TradingSystem

log = logging.getLogger(__name__)


def run_scheduled(system: TradingSystem) -> None:
    interval_min = system.settings.poll_interval_minutes
    log.info("starting scheduled runner: every %d min", interval_min)

    def _job() -> None:
        try:
            report = system.run_cycle()
            log.info(
                "cycle done: %d signals, %d events, equity=%.0f%s",
                report.signals_collected, report.events_formed, report.equity,
                " [HALTED]" if report.halted else "",
            )
        except Exception:  # noqa: BLE001
            log.exception("cycle failed")

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler

        sched = BlockingScheduler(timezone="UTC")
        sched.add_job(_job, "interval", minutes=interval_min, next_run_time=None)
        _job()  # run once immediately
        sched.start()
    except ImportError:
        log.warning("apscheduler not installed; using simple sleep loop")
        while True:
            _job()
            time.sleep(interval_min * 60)
