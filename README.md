# Alpaca AI Trading Agents Hackathon

Autonomous options-trading agent for the [lablab.ai × Alpaca hackathon](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon)
(Aug 28 – Sep 4, 2026). **Paper trading only.**

## Design

Two-sleeve strategy behind a deterministic risk manager:

- **Core sleeve** — short-dated (0–5 DTE) defined-risk premium selling
  (credit spreads / iron condors) on SPY, QQQ, XSP.
- **Catalyst sleeve** — LLM (Claude) scans news + earnings for IV-crush and
  directional plays, expressed as defined-risk debit spreads.

Pipeline per cycle: `Research → Strategy → Risk (veto power) → Execution`,
with every proposal, veto, order, and fill written to a SQLite decision
journal — the source for Telegram reports and the dashboard.

## Layout

- `src/trader/broker/` — Alpaca clients, options chain, MLEG order builder
- `src/trader/agents/` — research / strategy / risk / execution agents
- `src/trader/journal/` — SQLite decision journal
- `src/trader/notify/` — Telegram reporting
- `config/settings.yaml` — strategy parameters and hard risk limits
- `scripts/verify_setup.py` — end-to-end environment check

## Setup

```bash
conda create -n alpaca-trading python=3.12 -y
conda run -n alpaca-trading pip install -r requirements.txt
cp .env.example .env   # then fill in keys
conda run -n alpaca-trading python scripts/verify_setup.py
```
