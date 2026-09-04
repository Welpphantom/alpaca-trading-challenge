"""Risk agent: deterministic gates with veto power. No LLM in this file —
these limits are unconditionally enforced and nothing can loosen them at
runtime; config/settings.yaml is the ceiling.

Gates:
  1. Daily loss kill switch   — blocks NEW risk for the day (managing/closing always allowed)
  2. Drawdown kill switch     — blocks new risk + requires flatten (competition-terminal)
  3. Per-trade max loss       — shrinks qty to fit, vetoes if even 1 lot exceeds
  4. Open-risk budget         — shrinks qty to fit remaining budget
  5. Position count
  6. Contracts per order      — shrinks
  7. Weekend rule             — Friday entries must expire same day
  8. Market hours + buffers   — open, past opening buffer, before closing buffer

Kill switches (1, 2) fire only via BreachTracker: sustained, sanity-checked
breaches — see debounce.py. Feed readings via observe_equity() each cycle.
"""

import math
from datetime import datetime

from trader.agents.base import AccountState, RiskDecision, TradeProposal, Verdict
from trader.agents.debounce import BreachTracker


class RiskAgent:
    def __init__(self, risk_cfg: dict, starting_equity: float, journal=None, notifier=None):
        self.cfg = risk_cfg
        self.starting_equity = starting_equity
        self.journal = journal
        self.notifier = notifier
        d = risk_cfg["debounce"]
        self.daily_kill = BreachTracker(
            d["daily_loss"]["readings"], d["daily_loss"]["min_span_seconds"])
        self.drawdown_kill = BreachTracker(
            d["drawdown_flatten"]["readings"], d["drawdown_flatten"]["min_span_seconds"])
        self._alerted = set()

    # ── kill-switch feed (called once per management cycle) ──────────────

    def observe_equity(self, ts: datetime, equity: float, pnl_today: float, valid: bool) -> None:
        """valid=False when the reading failed data sanity — pauses the clocks."""
        self.daily_kill.record(
            ts, breached=pnl_today <= -self.cfg["max_daily_loss_usd"], valid=valid)
        self.drawdown_kill.record(
            ts,
            breached=equity <= self.starting_equity - self.cfg["max_total_drawdown_usd"],
            valid=valid,
        )
        for name, tracker in (("daily_loss", self.daily_kill),
                              ("drawdown_flatten", self.drawdown_kill)):
            if tracker.confirmed and name not in self._alerted:
                self._alerted.add(name)
                self._alert(f"🛑 <b>Kill switch confirmed: {name}</b>\n"
                            f"Equity ${equity:,.0f} · day P&amp;L ${pnl_today:,.0f}")

    def reset_daily(self) -> None:
        """Call at the start of each trading day."""
        self.daily_kill._breach_ts.clear()
        self._alerted.discard("daily_loss")

    @property
    def flatten_required(self) -> bool:
        return self.drawdown_kill.confirmed

    # ── proposal evaluation ──────────────────────────────────────────────

    def evaluate(self, proposal: TradeProposal, state: AccountState) -> RiskDecision:
        reasons: list[str] = []
        vetoed = False

        def fail(msg: str):
            nonlocal vetoed
            vetoed = True
            reasons.append(f"FAIL {msg}")

        # 1 & 2 — kill switches
        if self.daily_kill.confirmed:
            fail(f"gate1 daily-loss kill switch active (day P&L ${state.pnl_today:,.0f} "
                 f"<= -${self.cfg['max_daily_loss_usd']:,})")
        else:
            reasons.append("pass gate1 daily-loss")
        if self.drawdown_kill.confirmed:
            fail(f"gate2 drawdown kill switch active (equity ${state.equity:,.0f}) — flatten mode")
        else:
            reasons.append("pass gate2 drawdown")

        # 8 — market hours + buffers (cheap, checked before sizing)
        if not state.market_open:
            fail("gate8 market closed")
        elif state.minutes_since_open < self.cfg["entry_buffer_open_minutes"]:
            fail(f"gate8 within opening buffer ({state.minutes_since_open:.0f}m "
                 f"< {self.cfg['entry_buffer_open_minutes']}m)")
        elif state.minutes_to_close < self.cfg["entry_buffer_close_minutes"]:
            fail(f"gate8 within closing buffer ({state.minutes_to_close:.0f}m to close)")
        else:
            reasons.append("pass gate8 market hours")

        # 7 — weekend rule
        if (self.cfg["no_new_risk_into_weekend"] and state.is_friday
                and proposal.expiry > state.today):
            fail(f"gate7 weekend rule: Friday entry expiring {proposal.expiry} (must be 0DTE)")
        else:
            reasons.append("pass gate7 weekend rule")

        # 5 — position count
        if state.open_positions >= self.cfg["max_positions"]:
            fail(f"gate5 position count {state.open_positions} >= {self.cfg['max_positions']}")
        else:
            reasons.append(f"pass gate5 positions ({state.open_positions}/{self.cfg['max_positions']})")

        # 3, 4, 6 — sizing (shrink-before-veto)
        per_lot = proposal.max_loss_per_lot_usd
        if per_lot <= 0:
            fail(f"gate3 invalid per-lot risk ${per_lot}")
            qty = 0
        else:
            by_trade = math.floor(self.cfg["max_risk_per_trade_usd"] / per_lot)
            by_budget = math.floor(
                max(0.0, self.cfg["max_open_risk_usd"] - state.open_risk_usd) / per_lot)
            qty = min(proposal.qty, by_trade, by_budget, self.cfg["max_contracts_per_order"])
            if qty < 1:
                fail(f"gate3/4 no size fits: per-lot ${per_lot:,.0f}, "
                     f"per-trade cap ${self.cfg['max_risk_per_trade_usd']:,}, "
                     f"budget remaining ${self.cfg['max_open_risk_usd'] - state.open_risk_usd:,.0f}")
            elif qty < proposal.qty:
                reasons.append(
                    f"pass gate3/4/6 with SHRINK {proposal.qty} -> {qty} lots "
                    f"(risk ${per_lot * qty:,.0f})")
            else:
                reasons.append(f"pass gate3/4/6 full size ({qty} lots, risk ${per_lot * qty:,.0f})")

        decision = RiskDecision(
            verdict=Verdict.VETOED if vetoed else Verdict.APPROVED,
            reasons=reasons,
            adjusted_qty=None if vetoed else qty,
        )
        self._journal(proposal, state, decision)
        if vetoed:
            from trader.notify.telegram import esc
            fails = "\n".join(f"· {esc(r[5:])}" for r in reasons if r.startswith("FAIL"))
            self._alert(
                f"🚫 <b>Veto</b> — {esc(proposal.underlying)} "
                f"{esc(proposal.structure.replace('_', ' '))} × {proposal.qty}\n{fails}")
        return decision

    # ── plumbing ─────────────────────────────────────────────────────────

    def _journal(self, proposal, state, decision) -> None:
        if self.journal:
            self.journal.log(
                kind="veto" if decision.verdict == Verdict.VETOED else "approval",
                agent="risk",
                symbol=proposal.underlying,
                payload={
                    "structure": proposal.structure,
                    "requested_qty": proposal.qty,
                    "adjusted_qty": decision.adjusted_qty,
                    "per_lot_risk": proposal.max_loss_per_lot_usd,
                    "reasons": decision.reasons,
                    "equity": state.equity,
                    "pnl_today": state.pnl_today,
                    "open_risk": state.open_risk_usd,
                },
                rationale=proposal.rationale,
            )

    def _alert(self, text: str) -> None:
        if self.notifier:
            try:
                self.notifier.send(text)
            except Exception:
                pass  # reporting failure must never affect trading logic
