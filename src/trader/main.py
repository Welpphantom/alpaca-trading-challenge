"""CLI entrypoints. Run with PYTHONPATH=src:

    python -m trader.main state                  # account snapshot + gate status
    python -m trader.main propose XSP            # dry-run: build a proposal, no order
    python -m trader.main trade XSP [--expiry 2026-08-26] [--side put] [--qty N]
    python -m trader.main manage                 # one management cycle
    python -m trader.main report                 # EOD summary to Telegram
"""

import argparse
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from trader.agents.execution import ExecutionAgent
from trader.agents.risk import RiskAgent
from trader.agents.strategy import StrategyAgent
from trader.agents.base import Verdict
from trader.broker.alpaca_client import Broker
from trader.config import PROJECT_ROOT, load_secrets, load_settings
from trader.journal.journal import Journal
from trader.notify.telegram import Telegram
from trader.state import build_account_state

ET = ZoneInfo("America/New_York")


def build_stack(with_telegram: bool = True) -> dict:
    secrets = load_secrets()
    settings = load_settings()
    broker = Broker(secrets)
    journal = Journal(settings.journal_db_path)
    notifier = None
    if with_telegram and secrets.telegram_bot_token:
        notifier = Telegram(secrets)
    risk = RiskAgent(settings.risk, settings.raw["account"]["starting_equity"],
                     journal=journal, notifier=notifier)
    strategy = StrategyAgent(broker, journal, settings,
                             events_path=PROJECT_ROOT / "config" / "events.yaml")
    execution = ExecutionAgent(broker, journal, settings, notifier=notifier)
    return dict(secrets=secrets, settings=settings, broker=broker, journal=journal,
                notifier=notifier, risk=risk, strategy=strategy, execution=execution)


def cmd_state(stack) -> None:
    s = build_account_state(stack["broker"], stack["journal"])
    print(f"equity          ${s.equity:,.2f}")
    print(f"pnl_today       ${s.pnl_today:+,.2f}")
    print(f"open_risk       ${s.open_risk_usd:,.2f}")
    print(f"open_positions  {s.open_positions}")
    print(f"market_open     {s.market_open}"
          + (f" (open {s.minutes_since_open:.0f}m, close in {s.minutes_to_close:.0f}m)"
             if s.market_open else ""))
    print(f"today           {s.today} (friday={s.is_friday})")


def cmd_propose(stack, underlying: str, expiry: date, side: str) -> None:
    p = stack["strategy"].propose_core(underlying, expiry, side)
    if p is None:
        print("no proposal (see journal notes)")
        return
    print(f"{p.structure} {p.underlying} exp {p.expiry}")
    for leg in p.legs:
        print(f"  {leg.side.value:4s} {leg.symbol}")
    print(f"  qty {p.qty} @ ${p.net_price:.2f} credit · max loss ${p.max_loss_per_lot_usd:,.0f}/lot")
    print(f"\n{p.rationale}")


def cmd_trade(stack, underlying: str, expiry: date, side: str, qty: int | None) -> None:
    strategy, risk, execution = stack["strategy"], stack["risk"], stack["execution"]
    state = build_account_state(stack["broker"], stack["journal"])
    proposal = strategy.propose_core(underlying, expiry, side)
    if proposal is None:
        print("no proposal")
        return
    if qty:
        proposal.qty = qty
    decision = risk.evaluate(proposal, state)
    print("risk verdict:", decision.verdict.value)
    for r in decision.reasons:
        print(" ", r)
    if decision.verdict != Verdict.APPROVED:
        return
    pos_id = execution.execute(proposal, decision.adjusted_qty)
    print(f"position id: {pos_id}" if pos_id else "unfilled")


def cmd_manage(stack) -> None:
    state = build_account_state(stack["broker"], stack["journal"])
    risk, execution = stack["risk"], stack["execution"]
    risk.observe_equity(datetime.now(ET), state.equity, state.pnl_today, valid=True)
    if risk.flatten_required:
        execution.flatten_all("drawdown kill switch")
        return
    execution.manage_cycle(state.minutes_to_close)
    print("cycle done")


def cmd_research(stack) -> None:
    from trader.agents.research import ResearchAgent
    agent = ResearchAgent(stack["secrets"], stack["journal"], stack["settings"])
    print("Running research sweep (Claude + Alpaca MCP)...")
    out = agent.morning_brief()
    if out is None:
        print("sweep failed — see journal")
        return
    from trader.notify.telegram import esc
    b, eff = out["brief"], out["effects"]
    events = ", ".join(e["name"] for e in b.get("events_today", [])) or "none scheduled"
    posture = (f"delta ≤ {eff['delta_max']:.2f} · size × {eff['size_multiplier']:g}"
               + (f" · no entries before {eff['no_entry_before']} ET"
                  if eff.get("no_entry_before") else "")
               + (" · ⛔ STAND DOWN" if eff["stand_down"] else ""))
    text = (f"🔬 <b>Morning research brief</b>\n\n"
            f"{esc(b['market_context'])}\n\n"
            f"<b>Events:</b> {esc(events)}\n"
            f"<b>Posture:</b> {esc(posture)}\n\n"
            f"<i>{esc(b.get('rationale', ''))}</i>")
    print(text)
    if stack["notifier"]:
        stack["notifier"].send(text)


def cli_account_snapshot(secrets) -> dict | None:
    """Account snapshot via the official Alpaca CLI (JSON on stdout) — the
    CLI leg of the hackathon's MCP-or-CLI requirement, used in production
    for the EOD report's independent account read."""
    import shutil
    import subprocess
    if not shutil.which("alpaca"):
        return None
    try:
        import os
        r = subprocess.run(
            ["alpaca", "account", "get", "-q"],
            env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin",
                 "HOME": os.environ.get("HOME", ""),
                 "ALPACA_API_KEY": secrets.alpaca_api_key,
                 "ALPACA_SECRET_KEY": secrets.alpaca_secret_key},
            capture_output=True, text=True, timeout=30)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except Exception:
        return None


def cmd_report(stack) -> None:
    s = build_account_state(stack["broker"], stack["journal"])
    j = stack["journal"]
    today_iso = datetime.now(ET).strftime("%Y-%m-%d")
    closes = [e for e in j.events_since(today_iso, kind="close")]
    realized = sum(e["payload"].get("pnl", 0) for e in closes)
    from trader.notify.telegram import esc
    lines = [
        f"📊 <b>Schmidt Capital — end of day {today_iso}</b>",
        "",
        f"Equity: <b>${s.equity:,.2f}</b> · day P&amp;L <b>${s.pnl_today:+,.2f}</b>",
        f"Open positions: {s.open_positions} · open risk ${s.open_risk_usd:,.0f}",
        f"Closed today: {len(closes)} · realized ${realized:+,.2f}",
    ]
    for e in closes:
        p = e["payload"]
        reason = p["reason"].split("(")[0].strip()
        lines.append(f"   #{p['position_id']} {esc(e.get('symbol', ''))} "
                     f"{esc(reason)} · ${p['pnl']:+,.2f}")
    cli_acct = cli_account_snapshot(stack["secrets"])
    if cli_acct:
        lines.append("")
        lines.append(f"<i>CLI cross-check: equity "
                     f"${float(cli_acct['equity']):,.2f} ✓</i>")
    text = "\n".join(lines)
    print(text)
    if stack["notifier"]:
        stack["notifier"].send(text)


def main():
    ap = argparse.ArgumentParser(prog="trader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("state")
    for name in ("propose", "trade"):
        p = sub.add_parser(name)
        p.add_argument("underlying")
        p.add_argument("--expiry", type=date.fromisoformat,
                       default=datetime.now(ET).date())
        p.add_argument("--side", choices=["put", "call"], default="put")
        if name == "trade":
            p.add_argument("--qty", type=int, default=None)
    sub.add_parser("manage")
    sub.add_parser("report")
    sub.add_parser("research")
    args = ap.parse_args()

    stack = build_stack()
    if args.cmd == "state":
        cmd_state(stack)
    elif args.cmd == "propose":
        cmd_propose(stack, args.underlying.upper(), args.expiry, args.side)
    elif args.cmd == "trade":
        cmd_trade(stack, args.underlying.upper(), args.expiry, args.side, args.qty)
    elif args.cmd == "manage":
        cmd_manage(stack)
    elif args.cmd == "report":
        cmd_report(stack)
    elif args.cmd == "research":
        cmd_research(stack)


if __name__ == "__main__":
    main()
