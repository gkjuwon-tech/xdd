# xdd — Autonomous Trading Agent

An autonomous agent that reads **news, Reddit/X, and quantitative market data**,
forms and self-critiques trading hypotheses, sizes them under hard risk
guardrails, and executes — then reviews every closed trade to learn. Not a
macro bot: it reasons, argues with itself, and leaves an auditable trail for
every decision.

See [`docs/PRODUCT_PLAN.md`](docs/PRODUCT_PLAN.md) for the full design.

## Why it's an *agent*, not a bot

The cognitive loop (OODA + reflection):

```
OBSERVE ─▶ ORIENT ─▶ DECIDE ─▶ ACT ─▶ REFLECT ─┐
  ▲  news/social/market   Analyst   Risk    broker   Reviewer │
  └────────────── long-term lesson memory ◀──────────────────┘
```

Specialized sub-agents keep it honest:

| Agent | Role |
|-------|------|
| **Analyst** | Synthesizes narrative **and** market data into a calibrated hypothesis |
| **Skeptic** | Adversarially attacks it — can only *lower* confidence, flags manipulation |
| **Risk engine** | Deterministic, holds **final veto**; no LLM can override a guardrail |
| **Reviewer** | Post-mortem on every close → reusable lesson + calibration data |

## Key properties

- **Market-data synthesis** — every ticker gets returns, RSI, volatility,
  volume z-score, and trend, merged with the qualitative narrative. Tickers
  with no news still get a market snapshot.
- **Survival-first risk** — per-ticker cap, cash floor, daily-loss halt,
  drawdown circuit breaker, fractional-Kelly sizing, fee-viability check.
- **Full auditability** — every signal, hypothesis, critique, decision, and
  fill is written to an append-only log with its reasoning.
- **Calibration** — the agent's stated confidence is measured against realized
  hit-rate and discounted when over-confident.
- **Safe by default** — paper trading runs autonomously; live trading requires
  human approval. A kill switch halts and liquidates instantly.

## Stack

- **LLM:** DeepSeek V4 Flash (OpenAI-compatible; chosen for cost/latency over
  frontier models). Swap any OpenAI-compatible endpoint via env.
- **Broker:** local paper broker (default) or Alpaca (paper/live), US equities + crypto.
- **Data:** news RSS, Reddit JSON, X adapter (token-gated), quantitative market data.
- **Storage:** SQLite (audit log, positions, calibration, memory).
- Python 3.10+, pydantic, httpx, FastAPI, APScheduler. No heavyweight ML deps.

## Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Configure

Copy `.env.example` to `.env` and fill in what you need. Everything runs
offline with the stub LLM and paper broker out of the box.

```bash
export XDD_LLM_API_KEY=sk-...            # DeepSeek key (omit to run the offline stub)
export XDD_BROKER_BACKEND=paper          # or "alpaca"
```

## Run

```bash
xdd run-once      # one full cognitive cycle, prints the report
xdd run           # scheduled batch runner (N cycles/day)
xdd dashboard     # web UI at http://127.0.0.1:8000
xdd status        # portfolio snapshot
xdd backtest --days 120                  # point-in-time replay + metrics
xdd kill / xdd release                   # engage / release the kill switch
```

Fully-offline dry run (no keys, no network):

```bash
XDD_LLM_USE_STUB=true XDD_DATA_NEWS_RSS_URLS='[]' \
XDD_DATA_REDDIT_SUBREDDITS='[]' xdd run-once
```

## Test

```bash
pytest -q      # 24 hermetic offline tests
```

## Roadmap

M1 data skeleton · M2 agents · M3 risk+execution · M4 orchestration+observability ·
M5 backtester ✅ — next: live-paper validation (4 weeks), then human-approved
small-capital live. See the plan doc for milestones M6–M7.

## ⚠️ Disclaimer

Personal research/experiment. Not investment advice. Real trading is real
financial activity subject to your jurisdiction's regulations and broker terms;
losses are the operator's responsibility. Start with paper trading.
