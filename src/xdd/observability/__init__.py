"""Observability: logging, kill switch, and the dashboard."""

from xdd.observability.killswitch import KillSwitch
from xdd.observability.logging_setup import setup_logging

__all__ = ["KillSwitch", "setup_logging"]
