# Submission form text (paste-ready)

**Project title:** Schmidt Capital — Autonomous Options Trading Agent

**Short description:**
An autonomous options-trading agent that sells defined-risk credit spreads on
Alpaca — Claude reads the market through the official MCP server each morning
and can only make the system more conservative; eight deterministic risk gates
with debounced kill switches decide everything else. Every decision is
journaled with written rationale on a live dashboard.

**Long description:**
Schmidt Capital is a two-sleeve, defined-risk options book trading XSP credit
spreads (0–5 DTE, ~15Δ) on Alpaca paper trading, fully autonomous from morning
research to exit.

THE AI — Each morning a research agent (Claude, via the Claude Agent SDK)
connects to Alpaca's official MCP server and reads the market: snapshots,
news, movers, option chains, plus the macro calendar via web search. It sets
the day's posture — delta caps, size multipliers, entry blackouts. Its
influence is tighten-only and enforced in code: every recommendation is
clamped against config, and order-placing MCP tools are both whitelisted out
and explicitly banned. On day one it caught an error in our static event
calendar (the new Fed Chair's Jackson Hole keynote on kickoff morning) and
set the entry blackout accordingly.

THE RISK MACHINERY — Eight deterministic gates evaluate every order: daily
and competition kill switches, per-trade and portfolio risk budgets with
shrink-before-veto sizing, position/order caps, weekend and market-hours
rules. Kill switches and stops fire only on sustained, sanity-checked
breaches — a data glitch can cause nothing, never a liquidation. All exits
are re-pegged limit orders. Validated live: the system rode a −$94 dip back
to green without panicking, stopped positions at 1–2× credit in a selloff
instead of taking wing-sized losses, and flattened the entire book an hour
before the judging deadline so all P&L is realized.

THE ALPACA STACK — Trading API for atomic MLEG spread execution (signed net
pricing, close intents, buying-power-equals-defined-risk verified live); MCP
server as the research agent's entire market surface; the official CLI as an
independent equity cross-check in every end-of-day report; everything built
and shaken down in the paper environment across two full pre-kickoff sessions.

Python 3.12 · SQLite decision journal · Telegram reporting · Streamlit
dashboard showing the live account and the agent's complete decision journal.

**Tags:** Alpaca, Claude, MCP, Options, Trading Agent, Python, Streamlit

**Links:**
- Repo: https://github.com/Welpphantom/alpaca-trading-challenge
- Demo (dashboard): [STREAMLIT URL — fill before submitting]
- Alpaca paper account ID: PA3KGE66JM72
