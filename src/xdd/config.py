"""Central configuration, loaded from environment / .env.

All tunable knobs live here so the rest of the code never reads ``os.environ``
directly. Secrets (API keys) are read from the environment and never logged.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    """LLM provider settings.

    Defaults target DeepSeek V4 Flash via its OpenAI-compatible endpoint,
    chosen over frontier models for cost and latency. Point ``base_url`` /
    ``model`` at any OpenAI-compatible provider to switch.
    """

    model_config = SettingsConfigDict(env_prefix="XDD_LLM_", extra="ignore")

    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-v4-flash"
    api_key: str = ""
    # Reasoning budget hint for OpenAI-compatible "reasoning effort" if supported.
    temperature: float = 0.4
    max_tokens: int = 2048
    timeout_seconds: float = 60.0
    # When true (or no api_key), agents fall back to the deterministic stub LLM
    # so the whole pipeline runs offline for tests and dry runs.
    use_stub: bool = False


class RiskSettings(BaseSettings):
    """Hard guardrails and sizing parameters. These are the survival knobs."""

    model_config = SettingsConfigDict(env_prefix="XDD_RISK_", extra="ignore")

    seed_capital: float = 150000.0  # KRW, matching the ~10-20만원 seed
    currency: str = "KRW"
    max_position_pct: float = 0.25  # per-ticker cap as fraction of equity
    min_cash_pct: float = 0.20  # always keep this much in cash
    daily_loss_limit_pct: float = 0.05  # halt trading for the day past this
    max_drawdown_pct: float = 0.15  # circuit breaker: liquidate + stop
    default_stop_loss_pct: float = 0.08
    default_take_profit_pct: float = 0.15
    min_order_notional: float = 5000.0  # skip orders too small to beat fees
    fee_pct: float = 0.001  # round-trip fee estimate per side
    kelly_fraction: float = 0.25  # use quarter-Kelly
    min_confidence_to_trade: float = 0.55
    max_gross_exposure_pct: float = 0.80  # 1 - min_cash_pct, enforced separately


class DataSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XDD_DATA_", extra="ignore")

    news_rss_urls: list[str] = Field(
        default_factory=lambda: [
            "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ]
    )
    reddit_subreddits: list[str] = Field(
        default_factory=lambda: ["stocks", "wallstreetbets", "investing"]
    )
    reddit_user_agent: str = "xdd-agent/0.1"
    x_bearer_token: str = ""  # X adapter is a stub unless this is set
    watchlist: list[str] = Field(
        default_factory=lambda: ["AAPL", "TSLA", "NVDA", "MSFT", "AMD", "BTC", "ETH"]
    )
    signal_window_hours: float = 12.0
    max_signals_per_poll: int = 200


class BrokerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XDD_BROKER_", extra="ignore")

    # "paper" (fully local, default) or "alpaca" (paper or live via Alpaca).
    backend: str = "paper"
    alpaca_key_id: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    # Live trading requires human approval per §autonomy decision.
    live_trading: bool = False
    require_human_approval: bool = True


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XDD_", extra="ignore")

    db_path: str = "xdd.db"
    poll_interval_minutes: int = 60  # scheduled-batch cadence (hourly by default)
    max_events_per_cycle: int = 8
    log_level: str = "INFO"

    llm: LLMSettings = Field(default_factory=LLMSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
