# Schmidt Capital — Autonomous Options Trading Agent

**Alpaca AI Trading Agents Hackathon · Aug 28 – Sep 4, 2026 · Account: `[JUDGING-ACCOUNT-ID]` · Solo entry**

**Results: [FINAL] equity $______ · P&L $______ (____%) · ___ trades · ___% win rate · max drawdown $______**

## Strategy

A two-sleeve, defined-risk options book on Alpaca paper trading. The **core sleeve** sells
short-dated (0–5 DTE) credit spreads and iron condors on XSP/SPY/QQQ at ~15-delta short
strikes (~1σ) — harvesting the variance risk premium, the one edge that reliably realizes
inside a single week because theta accrues every session. The **catalyst sleeve** expresses
event-driven views as small debit spreads. Every structure has defined max loss at entry;
exits are rule-based (60% profit-take, 2×-credit stop, expiry handling). An expiry ladder
refuses thin credit (a missing 15Δ trade becomes *no* trade, never a 30Δ trade), and all
positions expire by Sep 4 so P&L is realized inside the judging window.

## AI logic — the LLM proposes, deterministic code disposes

Four agents per cycle: **Research → Strategy → Risk (veto power) → Execution.**
Each morning the **research agent** — Claude, via the Claude Agent SDK — connects to
**Alpaca's official MCP server** and reads the market through its tools (snapshots, news,
movers, option chains; order-placing tools are whitelisted out *and* explicitly banned),
plus web search for the macro calendar. It emits a structured brief that adjusts the day's
posture: delta cap, size multiplier, entry blackouts, stand-down. Critically, its influence
is **tighten-only, enforced in code** — every recommendation is `min()`-ed against config,
so the LLM can make the system more careful but structurally cannot make it more aggressive.
(It earned its keep on day one: it caught that our static calendar had the wrong Friday
event — the new Fed Chair's Jackson Hole keynote — and set the entry blackout accordingly.)
Every proposal, veto, fill, and brief is journaled with written rationale (SQLite), feeding
Telegram reports and the live dashboard: the agent explains every decision it ever made.

## Risk gates

Eight deterministic gates evaluate every order — no LLM in the loop: **(1)** daily-loss
kill switch (−2%: blocks new risk, never risk-reducing actions); **(2)** competition
drawdown kill switch (−5%: flatten + freeze); **(3)** per-trade max loss $1,500 with
shrink-before-veto sizing; **(4)** portfolio open-risk budget $10,000; **(5)** max 8
positions; **(6)** max 10 contracts/order; **(7)** weekend rule (Friday entries must be
0DTE); **(8)** market hours with open/close buffers. Kill switches fire only on
**sustained, sanity-checked breaches** — N consecutive valid readings over minutes, where
readings failing data-quality checks (crossed/stale/thin quotes, implausible jumps,
broker-vs-computed equity disagreement) pause the clock rather than trigger action: a data
glitch can cause *nothing*, never a liquidation. Exits are always limit orders, re-pegged
toward the market — never market orders into an options book. Live validation: a position
that dipped to −$94 intraday recovered fully because the debounced stop refused to panic;
a hair-trigger stop would have realized the loss at the low.

## Alpaca infrastructure

**Trading API** (alpaca-py): multi-leg **MLEG** orders for atomic spread execution
(signed net limit price; `*_TO_CLOSE` intents on exits; buying-power reduction verified
live to equal defined max loss), positions, clock/calendar, portfolio history.
**MCP server** (official): the research agent's entire market-reading surface — core to
the AI logic above. **CLI** (official): independent account cross-check in every
end-of-day report — two code paths must agree on equity. **Paper environment:** two full
shakedown sessions before kickoff verified every path live (fills, re-pegs, profit-takes,
kill-switch plumbing, restart-safety including startup sweep of orphaned orders).
The autonomous loop runs 60-second management cycles all session; a hard kickoff gate
guaranteed zero order activity before the competition began. Stack: Python 3.12, SQLite
journal, Telegram reporting, Streamlit dashboard (live account + full decision journal).
