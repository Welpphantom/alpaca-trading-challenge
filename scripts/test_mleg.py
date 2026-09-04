"""Live MLEG verification (run while market is open, DEV account only).

Places a 1-lot XSP put credit spread through the full pipeline, records
buying power before/after fill, then closes it immediately. Answers:
  1. Does Alpaca accept MLEG orders (and the signed limit_price convention)?
  2. What's the buying-power reduction for a defined-risk spread?
  3. Do our re-peg / fill-poll / journal / Telegram paths work end to end?

Cost of the test: ~one bid-ask spread crossing (a few dollars of paper money).
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trader.agents.base import Verdict            # noqa: E402
from trader.main import build_stack, build_account_state  # noqa: E402

ET = ZoneInfo("America/New_York")


def bp(broker):
    a = broker.account()
    return {
        "equity": float(a.equity),
        "cash": float(a.cash),
        "buying_power": float(a.buying_power),
        "options_bp": float(getattr(a, "options_buying_power", 0) or 0),
    }


def show(label, d, prev=None):
    line = f"{label:22s}" + "  ".join(f"{k} ${v:,.0f}" for k, v in d.items())
    print(line)
    if prev:
        deltas = {k: d[k] - prev[k] for k in d}
        print(f"{'  delta':22s}" + "  ".join(f"{k} {v:+,.0f}" for k, v in deltas.items()))


def main():
    stack = build_stack()
    broker, journal = stack["broker"], stack["journal"]
    state = build_account_state(broker, journal)
    if not state.market_open:
        print("Market closed — run this during RTH.")
        sys.exit(1)

    today = datetime.now(ET).date()
    print(f"=== MLEG live test · {today} ===\n")
    bp0 = bp(broker)
    show("before open:", bp0)

    proposal = stack["strategy"].propose_core_ladder("XSP", "put")
    if proposal is None:
        print("\nNo viable proposal on any expiry (see journal) — try again shortly.")
        sys.exit(1)
    proposal.qty = 1
    print(f"\nproposal: {proposal.rationale}\n")

    decision = stack["risk"].evaluate(proposal, state)
    print("risk:", decision.verdict.value)
    for r in decision.reasons:
        print("  ", r)
    if decision.verdict != Verdict.APPROVED:
        sys.exit(1)

    pos_id = stack["execution"].execute(proposal, 1)
    if pos_id is None:
        print("\nOrder did not fill — MLEG acceptance still verified if no rejection above.")
        sys.exit(1)

    bp1 = bp(broker)
    print()
    show("after fill:", bp1, bp0)
    per_lot = proposal.max_loss_per_lot_usd
    print(f"\nexpected BP reduction if margin = defined risk: ~${per_lot:,.0f}")

    pos = next(p for p in journal.open_positions() if p["id"] == pos_id)
    mark = stack["execution"].spread_mark(pos)
    print(f"\nclosing at mark {mark} ...")
    ok = stack["execution"].close(pos, mark, "mleg test complete")
    bp2 = bp(broker)
    print()
    show("after close:", bp2, bp1)
    print("\n=== test", "PASSED" if ok else "PARTIAL (close unfilled — retry manage)", "===")


if __name__ == "__main__":
    main()
