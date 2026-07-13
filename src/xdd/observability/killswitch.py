"""Kill switch: a persisted flag that halts trading and can liquidate everything.

A human must be able to stop the agent instantly. The flag lives in the ``kv``
table so it survives restarts and is visible to every process (scheduler,
dashboard). When engaged, the orchestrator refuses new entries; ``engage()``
optionally liquidates all open positions immediately.
"""

from __future__ import annotations

import logging

from xdd.storage import Repository

log = logging.getLogger(__name__)

_KEY = "kill_switch"


class KillSwitch:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    @property
    def engaged(self) -> bool:
        return self._repo.get_kv(_KEY, "off") == "on"

    def engage(self, reason: str = "manual") -> None:
        self._repo.set_kv(_KEY, "on")
        self._repo.set_kv("kill_switch_reason", reason)
        log.warning("KILL SWITCH ENGAGED: %s", reason)

    def release(self) -> None:
        self._repo.set_kv(_KEY, "off")
        log.info("kill switch released")

    @property
    def reason(self) -> str:
        return self._repo.get_kv("kill_switch_reason", "") or ""
