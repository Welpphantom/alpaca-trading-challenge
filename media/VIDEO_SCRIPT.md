# Video script — ~3:30, single screen-recording pass

**Setup before recording (tab lineup, left to right):**
1. Streamlit dashboard (top of page — metrics + equity curve visible)
2. Dashboard scrolled to the decision journal, filtered to `research, veto, close`
3. `SLIDES.pdf` open at slide 2 (strategy)
4. Terminal: `trader.main research` output from this morning (scroll back), or Telegram web with the morning brief visible
5. Telegram web/app: today's feed (brief → fills → heartbeats)
6. GitHub repo page

QuickTime → New Screen Recording → record with microphone. Speak naturally;
pauses are fine. One continuous take; two or three attempts is normal.

---

**[0:00 — Tab 1: dashboard top]**
This is Schmidt Capital — an autonomous options-trading agent I built for the
Alpaca hackathon. What you're looking at is live: this equity curve is a real
Alpaca paper account that the agent has been trading by itself all week —
ten trades, every single one decided, executed, and managed with no human in
the loop. Final result: one hundred thousand and eighteen dollars — it finished green.

**[0:25 — Tab 3: slide 2]**
The strategy is deliberately boring: sell short-dated, defined-risk credit
spreads on index options and let time decay do the work — the one edge that
reliably shows up inside a single week. Every position has a known maximum
loss before it's ever opened. The interesting part isn't the strategy — it's
the machine around it.

**[0:50 — Tab 4/5: research brief]**
Every morning, Claude connects to Alpaca's official MCP server and reads the
market — prices, news, the macro calendar — and writes this brief. Here it's
flagging nonfarm payrolls this morning and tightening the day's risk posture. And here's
the key design rule of the whole system: the AI can only make the agent MORE
conservative. Every recommendation is clamped against config in code. The
model proposes — deterministic code disposes. It can't loosen a limit, and
its order-placing tools are stripped entirely.

**[1:30 — Tab 2: journal, vetoes + closes]**
Everything downstream is deterministic: eight risk gates check every trade —
position sizing, open-risk budgets, kill switches, event blackouts. This is
the decision journal: every proposal, every veto with the exact numbers,
every fill, every exit. My favorite entries are the refusals — on day one
the agent stood aside entirely because a new Fed Chair was speaking and
premium didn't clear its quality bar. A week later: seven wins out of ten, seventy percent — and every loss was
stop-sized, never wing-sized. Worst drawdown of the whole week: a hundred and
thirty-nine dollars.

**[2:20 — Tab 5: Telegram]**
I ran this from my phone all week. The agent briefs me every morning,
narrates every fill and veto, heartbeats every half hour, and reports every
close — including a CLI cross-check where a second, independent code path
confirms the account equity. When I traveled mid-week, nothing changed.

**[2:50 — Tab 6: repo, then back to Tab 1]**
The stack: Alpaca's Trading API for atomic multi-leg spreads — buying power
verified live to equal defined risk — the MCP server as the AI's eyes, the
CLI as an independent audit, all on the paper environment. Python, SQLite
journal, Streamlit dashboard, fully open source.

**[3:10 — Tab 1: dashboard]**
Schmidt Capital: an agent that explains every decision it ever made, refused
the trades it should have refused, and never once needed me to save it. An hour before the judging deadline, it
flattened its own book and stood down — nobody told it to; that was code.
Thanks for watching.
