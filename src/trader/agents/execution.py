"""Execution agent: approved proposals -> MLEG orders -> position management.

Order policy (both entries and exits): limit at the proposal/mark price,
polled ~20s, re-pegged toward the market by one step up to `MAX_REPEGS`
times, then cancelled. Never market orders on options.

Position management per cycle:
  - profit-take when the spread can be bought back at (1 - profit_take_pct) * credit
  - stop when mark >= stop_loss_multiple * credit, debounced (2 valid readings / 2 min)
  - forced close near expiry for physically-settled underlyings (SPY/QQQ);
    cash-settled index options (XSP/SPX) may expire on their own
"""

import time as time_mod
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

from alpaca.data.requests import OptionLatestQuoteRequest
from alpaca.trading.enums import OrderSide

from trader.agents.base import TradeProposal
from trader.agents.debounce import BreachTracker
from trader.broker.options import Leg, build_mleg_limit_order
from trader.broker.sanity import check_quote

CASH_SETTLED = {"XSP", "SPX", "SPXW"}
POLL_SECONDS = 20
MAX_REPEGS = 3
PEG_STEP = 0.05          # walk limit one step toward market per re-peg
EXPIRY_CLOSE_MIN = 45    # minutes before close to force-close physically-settled


class ExecutionAgent:
    def __init__(self, broker, journal, settings, notifier=None):
        self.broker = broker
        self.journal = journal
        self.settings = settings
        self.notifier = notifier
        self.core_cfg = settings.strategy["core"]
        sanity = settings.risk["sanity"]
        self._q_kwargs = dict(
            max_spread_pct_of_mid=sanity["max_leg_spread_pct_of_mid"],
            max_age_seconds=sanity["max_quote_age_seconds"],
        )
        d = settings.risk["debounce"]["position_stop"]
        self._stop_trackers: dict[int, BreachTracker] = {}
        self._stop_cfg = (d["readings"], d["min_span_seconds"])

    # ── quotes ───────────────────────────────────────────────────────────

    def _leg_quotes(self, symbols: list[str]) -> dict | None:
        """Fetch + sanity-check quotes for all legs; None if any leg fails."""
        quotes = self.broker.option_data.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=symbols))
        out = {}
        for sym in symbols:
            q = quotes.get(sym)
            if q is None:
                return None
            chk = check_quote(float(q.bid_price or 0), float(q.ask_price or 0),
                              q.timestamp, **self._q_kwargs)
            if not chk.ok:
                self.journal.log("note", "execution",
                                 {"msg": f"quote sanity failed {sym}: {chk.reason}"})
                return None
            out[sym] = q
        return out

    def spread_mark(self, position: dict) -> float | None:
        """Cost to close (buy back) one lot of a credit spread.

        Short legs (we buy back) need a strict, sane quote — a bad quote there
        means no mark. Long legs (we sell) are valued conservatively at their
        BID, which may legitimately be $0 for a nearly-worthless wing; a dead
        long-leg quote must never block managing the position (found live 8/27:
        zero-bid far wing froze the profit-take)."""
        symbols = [leg["symbol"] for leg in position["legs"]]
        quotes = self.broker.option_data.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=symbols))
        mark = 0.0
        for leg in position["legs"]:
            q = quotes.get(leg["symbol"])
            if q is None:
                return None
            bid, ask = float(q.bid_price or 0), float(q.ask_price or 0)
            if leg["side"] == "sell":
                chk = check_quote(bid, ask, q.timestamp, **self._q_kwargs)
                if not chk.ok:
                    self.journal.log("note", "execution", {
                        "msg": f"short-leg quote sanity failed {leg['symbol']}: {chk.reason}"})
                    return None
                mark += (bid + ask) / 2
            else:
                mark -= max(bid, 0.0)   # conservative: worthless wing sells for its bid
        return round(mark, 2)

    # ── order submission with re-pegging ─────────────────────────────────

    def _submit_and_work(self, legs: list[Leg], qty: int, price: float,
                         is_credit: bool, tag: str, closing: bool = False) -> dict | None:
        """Submit MLEG limit, re-peg toward market until filled or exhausted.
        Credit orders re-peg by LOWERING the credit; debit by RAISING the debit."""
        for attempt in range(MAX_REPEGS + 1):
            px = round(price - PEG_STEP * attempt if is_credit
                       else price + PEG_STEP * attempt, 2)
            if px <= 0.01:
                break
            order = self.broker.trading.submit_order(
                build_mleg_limit_order(legs, qty=qty, net_price=px,
                                       is_credit=is_credit, closing=closing))
            deadline = time_mod.time() + POLL_SECONDS
            while time_mod.time() < deadline:
                o = self.broker.trading.get_order_by_id(order.id)
                if str(o.status) in ("OrderStatus.FILLED", "filled"):
                    fill_px = abs(float(o.filled_avg_price or px))
                    self.journal.log("fill", "execution", {
                        "tag": tag, "qty": qty, "limit": px, "fill": fill_px,
                        "attempt": attempt, "order_id": str(o.id)})
                    return {"order_id": str(o.id), "price": fill_px, "qty": qty}
                if str(o.status) in ("OrderStatus.CANCELED", "canceled",
                                     "OrderStatus.REJECTED", "rejected"):
                    self.journal.log("error", "execution", {
                        "tag": tag, "status": str(o.status), "limit": px})
                    return None
                time_mod.sleep(2)
            try:
                self.broker.trading.cancel_order_by_id(order.id)
            except Exception:
                pass  # may have filled in the race; next loop re-checks via new order
        self.journal.log("note", "execution",
                         {"msg": f"{tag}: unfilled after {MAX_REPEGS + 1} attempts"})
        return None

    # ── open ─────────────────────────────────────────────────────────────

    def execute(self, proposal: TradeProposal, qty: int) -> int | None:
        """Open an approved position. Returns journal position id, or None."""
        result = self._submit_and_work(
            proposal.legs, qty, proposal.net_price, proposal.is_credit,
            tag=f"open {proposal.underlying} {proposal.structure}")
        if result is None:
            return None
        pos_id = self.journal.open_position(
            underlying=proposal.underlying,
            structure=proposal.structure,
            legs=[{"symbol": l.symbol, "side": l.side.value, "ratio": l.ratio}
                  for l in proposal.legs],
            qty=result["qty"],
            net_price=result["price"],
            is_credit=proposal.is_credit,
            max_loss_per_lot_usd=proposal.max_loss_per_lot_usd,
            expiry=proposal.expiry.isoformat(),
        )
        from trader.notify.telegram import esc
        kind = "credit" if proposal.is_credit else "debit"
        self._notify(
            f"✅ <b>Opened #{pos_id}</b> — {esc(proposal.underlying)} "
            f"{esc(proposal.structure.replace('_', ' '))} × {result['qty']}\n"
            f"Fill: ${result['price']:.2f} {kind} · "
            f"max risk ${proposal.max_loss_per_lot_usd * result['qty']:,.0f} · "
            f"expires {proposal.expiry}\n\n"
            f"<i>{esc(proposal.rationale)}</i>")
        return pos_id

    # ── close ────────────────────────────────────────────────────────────

    def close(self, position: dict, mark: float, reason: str) -> bool:
        legs = [Leg(l["symbol"], OrderSide.BUY if l["side"] == "sell" else OrderSide.SELL,
                    l["ratio"]) for l in position["legs"]]
        result = self._submit_and_work(
            legs, position["qty"], max(mark, 0.02), is_credit=False,
            tag=f"close #{position['id']} ({reason})", closing=True)
        if result is None:
            from trader.notify.telegram import esc
            self._notify(f"⚠️ Close attempt for #{position['id']} "
                         f"({esc(reason)}) unfilled — will retry next cycle.")
            return False
        pnl = round((position["net_price"] - result["price"]) * 100 * position["qty"], 2)
        self.journal.close_position(position["id"], exit_price=result["price"],
                                    realized_pnl_usd=pnl)
        self.journal.log("close", "execution",
                         {"position_id": position["id"], "reason": reason,
                          "exit": result["price"], "pnl": pnl},
                         symbol=position["underlying"])
        from trader.notify.telegram import esc
        self._notify(f"{'🟢' if pnl >= 0 else '🔴'} <b>Closed #{position['id']}</b> — "
                     f"{esc(reason)}\nRealized P&amp;L: <b>${pnl:+,.2f}</b>")
        return True

    # ── management cycle ─────────────────────────────────────────────────

    def manage_cycle(self, minutes_to_close: float) -> None:
        now = datetime.now(timezone.utc)
        for pos in self.journal.open_positions():
            if not pos["is_credit"]:
                continue  # catalyst debit sleeve management added later
            mark = self.spread_mark(pos)
            tracker = self._stop_trackers.setdefault(
                pos["id"], BreachTracker(*self._stop_cfg))
            if mark is None:
                tracker.record(now, breached=False, valid=False)  # pause, no action
                continue

            credit = pos["net_price"]
            take_at = round(credit * (1 - self.core_cfg["profit_take_pct"]), 2)
            stop_at = round(credit * self.core_cfg["stop_loss_multiple"], 2)
            tracker.record(now, breached=mark >= stop_at, valid=True)

            expiry_today = pos["expiry"] == now.astimezone(ET).date().isoformat()
            must_close_expiry = (expiry_today
                                 and pos["underlying"] not in CASH_SETTLED
                                 and minutes_to_close <= EXPIRY_CLOSE_MIN)

            if mark <= take_at:
                self.close(pos, mark, f"profit take (mark {mark} <= {take_at})")
            elif tracker.confirmed:
                self.close(pos, mark, f"stop loss (mark {mark} >= {stop_at}, sustained)")
                self._stop_trackers.pop(pos["id"], None)
            elif must_close_expiry:
                self.close(pos, mark, "expiry close-out (physically settled)")

    def flatten_all(self, reason: str) -> None:
        for pos in self.journal.open_positions():
            mark = self.spread_mark(pos)
            if mark is not None:
                self.close(pos, mark, f"FLATTEN: {reason}")

    def _notify(self, text: str) -> None:
        if self.notifier:
            try:
                self.notifier.send(text)
            except Exception:
                pass
