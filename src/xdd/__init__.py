"""xdd — an autonomous news/social/market-signal trading agent.

See ``docs/PRODUCT_PLAN.md`` for the architecture. The package is layered:

    collectors  -> OBSERVE   (news, reddit, x, market data)
    signals     -> normalize/filter/event-formation
    agents      -> ORIENT/DECIDE/REFLECT (Analyst, Skeptic, Risk, Reviewer)
    risk        -> deterministic guardrails + sizing (final veto)
    execution   -> ACT (brokers)
    orchestrator-> the cognitive loop that ties it together
    storage     -> audit log + positions + calibration
    observability -> dashboard + kill switch
"""

__version__ = "0.1.0"
