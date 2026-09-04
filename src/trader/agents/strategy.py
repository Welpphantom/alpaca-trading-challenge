"""Strategy agent — core sleeve: delta-targeted defined-risk credit spreads.

Deterministic path: chain snapshot (with greeks) -> short strike nearest the
target delta -> wing `width` further OTM -> price off live mids -> TradeProposal.
Event-calendar effects (delta cap, size multiplier, entry blackout) are applied
here; the risk agent independently re-checks everything downstream.

The catalyst sleeve (LLM) plugs in later via the same TradeProposal type.
"""

import math
from datetime import date, datetime
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from alpaca.data.requests import OptionChainRequest
from alpaca.trading.enums import OrderSide

from trader.agents.base import TradeProposal
from trader.broker.bs import bs_delta, implied_vol, spot_from_parity
from trader.broker.options import (ChainRow, Leg, parse_occ, pick_credit_spread,
                                   scaled_credit_floor)
from trader.events import effects_for, entry_blocked, load_events

ET = ZoneInfo("America/New_York")

# Wing width per underlying (dollars of strike distance)
WIDTHS = {"XSP": 5.0, "SPY": 5.0, "QQQ": 5.0}


class StrategyAgent:
    def __init__(self, broker, journal, settings, events_path=None):
        self.broker = broker
        self.journal = journal
        self.settings = settings
        self.core_cfg = settings.strategy["core"]
        self.risk_cfg = settings.risk
        self.events = load_events(events_path) if events_path else []

    # ── chain access ─────────────────────────────────────────────────────

    RISK_FREE = 0.04

    def fetch_chain_rows(self, underlying: str, expiry: date, side: str) -> list[ChainRow]:
        """Chain rows with deltas — feed greeks when present, Black-Scholes
        fallback (spot via put-call parity from the same chain) when absent."""
        chain = self.broker.option_data.get_option_chain(
            OptionChainRequest(underlying_symbol=underlying, expiration_date=expiry)
        )
        all_rows: dict[str, list[ChainRow]] = {"put": [], "call": []}
        for symbol, snap in chain.items():
            meta = parse_occ(symbol)
            q = getattr(snap, "latest_quote", None)
            g = getattr(snap, "greeks", None)
            all_rows[meta["type"]].append(ChainRow(
                symbol=symbol,
                strike=meta["strike"],
                delta=getattr(g, "delta", None) if g else None,
                bid=float(getattr(q, "bid_price", 0) or 0),
                ask=float(getattr(q, "ask_price", 0) or 0),
                quote_ts=getattr(q, "timestamp", None) if q else None,
            ))

        rows = all_rows[side]
        if any(r.delta is None and r.bid > 0 for r in rows):
            rows = self._fill_deltas_bs(all_rows, side, expiry)
        return rows

    def _fill_deltas_bs(self, all_rows: dict, side: str, expiry: date) -> list[ChainRow]:
        from dataclasses import replace
        expiry_dt = datetime.combine(expiry, dt_time(16, 0), tzinfo=ET)
        t_years = max((expiry_dt - datetime.now(ET)).total_seconds(), 0) / (365.25 * 86400)

        live = {t: {r.strike: r for r in all_rows[t] if r.bid > 0 and r.ask > r.bid}
                for t in ("put", "call")}
        pairs = [(k, live["call"][k].mid, live["put"][k].mid)
                 for k in live["call"] if k in live["put"]]
        spot = spot_from_parity(pairs, self.RISK_FREE, t_years)
        if spot is None or t_years <= 0:
            return all_rows[side]

        out = []
        for r in all_rows[side]:
            if r.delta is None and r.bid > 0 and r.ask > r.bid:
                iv = implied_vol(r.mid, spot, r.strike, t_years,
                                 self.RISK_FREE, is_call=(side == "call"))
                if iv is not None:
                    r = replace(r, delta=bs_delta(spot, r.strike, t_years, iv,
                                                  self.RISK_FREE, is_call=(side == "call")))
            out.append(r)
        return out

    # ── core proposal ────────────────────────────────────────────────────

    def _research_effects(self, today: date) -> dict:
        """Today's research-agent effects, if a sweep ran. Tighten-only was
        already enforced when written; stale files (wrong date) are ignored."""
        import json
        from trader.config import PROJECT_ROOT
        path = PROJECT_ROOT / "data" / "research_effects.json"
        try:
            data = json.loads(path.read_text())
            if data.get("date") == today.isoformat():
                return data["effects"]
        except (OSError, ValueError, KeyError):
            pass
        return {}

    def propose_core(self, underlying: str, expiry: date,
                     side: str = "put") -> TradeProposal | None:
        now_et = datetime.now(ET)
        effects = effects_for(now_et.date(), self.events)

        research = self._research_effects(now_et.date())
        if research:
            if research.get("stand_down"):
                self._note(underlying, "research agent: STAND DOWN — no entries today")
                return None
            effects["names"] = effects["names"] + research.get("names", [])
            if "delta_max" in research:
                effects["delta_max"] = min(effects.get("delta_max", 1.0), research["delta_max"])
            if "size_multiplier" in research:
                effects["size_multiplier"] = min(effects.get("size_multiplier", 1.0),
                                                 research["size_multiplier"])
            if "no_entry_before" in research:
                from datetime import time as _t
                t = _t.fromisoformat(research["no_entry_before"])
                effects["no_entry_before"] = max(effects.get("no_entry_before", _t.min), t)

        block = entry_blocked(now_et, effects)
        if block:
            self._note(underlying, f"no entry: {block}")
            return None

        target = (self.core_cfg["target_short_delta_put"] if side == "put"
                  else self.core_cfg["target_short_delta_call"])
        if "delta_max" in effects:
            target = min(target, effects["delta_max"])

        width = WIDTHS[underlying]
        rows = self.fetch_chain_rows(underlying, expiry, side)
        floor = scaled_credit_floor(
            self.core_cfg.get("min_credit_frac", 0.10), target,
            ref_delta=self.core_cfg["target_short_delta_put"])
        picked = pick_credit_spread(rows, side=side, target_delta=target,
                                    width=width, min_credit_frac=floor)
        if picked is None:
            self._note(underlying, f"no viable {side} spread at ~{target:.0%}Δ "
                                   f"{expiry} ({len(rows)} contracts scanned)")
            return None
        short, long, credit = picked

        per_lot_risk = round((width - credit) * 100, 2)
        qty = min(
            math.floor(self.risk_cfg["max_risk_per_trade_usd"] / per_lot_risk),
            self.risk_cfg["max_contracts_per_order"],
        )
        qty = max(1, math.floor(qty * effects.get("size_multiplier", 1.0)))

        pop = 1 - abs(short.delta)
        rationale = (
            f"{underlying} {side} credit spread {short.strike:g}/{long.strike:g} exp {expiry}: "
            f"short leg at {abs(short.delta):.2f}Δ (~{pop:.0%} PoP), credit ${credit:.2f} on "
            f"${width:g} wings -> max loss ${per_lot_risk:,.0f}/lot. "
            f"Plan: take profit at {self.core_cfg['profit_take_pct']:.0%} of credit, "
            f"stop at {self.core_cfg['stop_loss_multiple']:g}x credit."
            + (f" Event effects today: {', '.join(effects['names'])}." if effects["names"] else "")
        )

        proposal = TradeProposal(
            underlying=underlying,
            structure=f"{side}_credit_spread",
            legs=[
                Leg(short.symbol, OrderSide.SELL),
                Leg(long.symbol, OrderSide.BUY),
            ],
            qty=qty,
            net_price=credit,
            is_credit=True,
            max_loss_per_lot_usd=per_lot_risk,
            expiry=expiry,
            rationale=rationale,
            source="core",
            tags=[f"delta:{abs(short.delta):.2f}", f"width:{width:g}"],
        )
        self.journal.log("proposal", "strategy", {
            "structure": proposal.structure, "short": short.symbol, "long": long.symbol,
            "credit": credit, "qty": qty, "per_lot_risk": per_lot_risk,
        }, rationale=rationale, symbol=underlying)
        return proposal

    def propose_core_ladder(self, underlying: str,
                            side: str = "put") -> TradeProposal | None:
        """Try expiries from dte_min upward; first one whose spread passes the
        credit floor wins. 0DTE at low delta often pays too little — the floor
        rejects it and the ladder falls through to a richer expiry. On Fridays
        only 0DTE is attempted (weekend rule would veto anything else)."""
        from datetime import timedelta
        today = datetime.now(ET).date()
        max_offset = 0 if today.weekday() == 4 else self.core_cfg["dte_max"]
        for offset in range(self.core_cfg["dte_min"], max_offset + 1):
            expiry = today + timedelta(days=offset)
            if expiry.weekday() >= 5:
                continue  # no weekend expiries
            try:
                p = self.propose_core(underlying, expiry, side)
            except Exception as e:
                self._note(underlying, f"ladder {expiry}: chain error {e}")
                continue
            if p is not None:
                return p
        return None

    def _note(self, symbol: str, msg: str) -> None:
        self.journal.log("note", "strategy", {"msg": msg}, symbol=symbol)
