"""Autonomous shakedown session (DEV account). Launch before market open:

  1. waits for market open + 16 min (gate 8 buffer)
  2. runs the MLEG verification test (open + immediate close, 1 lot)
  3. if it passes: opens one real core XSP position via the full pipeline
  4. manages every 60s (profit-take / debounced stop / kill switches) until close
  5. sweeps expired positions, sends an EOD report

All progress goes to Telegram. Designed to be left completely alone.
"""

import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from trader.agents.base import Verdict          # noqa: E402
from trader.notify.telegram import esc          # noqa: E402
from trader.main import build_stack             # noqa: E402
from trader.state import build_account_state    # noqa: E402

ET = ZoneInfo("America/New_York")
HEARTBEAT_SECONDS = 1800
ENTRY_RETRY_SECONDS = 3600   # re-attempt entries hourly; gates/dedup govern


def log(msg):
    print(f"[{datetime.now(ET):%H:%M:%S} ET] {msg}", flush=True)


def main():
    stack = build_stack()
    broker, journal, notifier = stack["broker"], stack["journal"], stack["notifier"]

    def tg(text):
        log(f"TG: {text.splitlines()[0]}")
        if notifier:
            try:
                notifier.send(text)
            except Exception:
                try:  # markdown parse failures: retry sanitized
                    notifier.send(text.replace("`", "'").replace("*", "").replace("_", " "))
                except Exception as e:
                    log(f"telegram failed twice: {e}")

    tg("🌙 <b>Runner armed</b>\nWaiting for market open + entry buffer. "
       "You can walk away — everything reports here.")

    # 0.1 ── HARD kickoff gate: absolutely no orders before NOT_BEFORE_ET ──
    # Competition rule (organizer-confirmed): trading on the judging account
    # must start AFTER kickoff. The US market opens 9:30 ET but kickoff is
    # 11:00 ET Fri — every order (verification test included) must wait.
    #   NOT_BEFORE_ET="2026-08-28T11:00"  (ISO, ET)
    not_before_raw = os.environ.get("NOT_BEFORE_ET")
    if not_before_raw:
        not_before = datetime.fromisoformat(not_before_raw).replace(tzinfo=ET)
        if datetime.now(ET) < not_before:
            tg(f"⛔ Kickoff gate: NO order activity before {not_before:%Y-%m-%d %H:%M} ET. "
               "Sleeping until then.")
            while datetime.now(ET) < not_before:
                time.sleep(30)
            tg("🏁 Kickoff gate passed — competition trading begins.")

    # 0 ── sweep stray working orders from a previous run ─────────────────
    # A killed process can leave a live limit order holding contracts, which
    # blocks every later close attempt with 403s (learned live 8/27).
    try:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        stray = broker.trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        for o in stray:
            broker.trading.cancel_order_by_id(o.id)
        if stray:
            tg(f"🧹 Cancelled {len(stray)} stray working order(s) from a previous run.")
    except Exception as e:
        log(f"stray-order sweep failed (continuing): {e}")

    # 0.5 ── morning research sweep (Claude + Alpaca MCP) ─────────────────
    effects_file = PROJECT_ROOT / "data" / "research_effects.json"
    already_swept = False
    try:
        import json as _json
        already_swept = (_json.loads(effects_file.read_text())["date"]
                         == datetime.now(ET).date().isoformat())
    except Exception:
        pass
    if os.environ.get("SKIP_RESEARCH") or already_swept:
        tg("⏭️ Research sweep already done today (or skipped).")
    else:
        tg("🔬 Running morning research sweep (Claude + Alpaca MCP)...")
        r = subprocess.run(
            [sys.executable, "-m", "trader.main", "research"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}, timeout=900)
        if r.returncode != 0:
            tg("⚠️ Research sweep failed — trading continues on static calendar only.")
            log(r.stdout + r.stderr)
        # success case: cmd_research already sent the brief to Telegram

    # 1 ── wait for open + buffer ─────────────────────────────────────────
    announced_open = False
    while True:
        try:
            clock = broker.clock()
            if clock.is_open:
                if not announced_open:
                    announced_open = True
                    tg("🔔 Market open. Holding through the 15-minute entry buffer.")
                state = build_account_state(broker, journal)
                if state.minutes_since_open >= 16:
                    break
                time.sleep(30)
            else:
                time.sleep(60)
        except Exception as e:
            log(f"wait loop error (retrying): {e}")
            time.sleep(60)

    # 2 ── MLEG verification: ONCE PER ACCOUNT, not daily ─────────────────
    # First session on a fresh account proves the whole order path with 1 lot.
    # After that it's pure P&L drag. A failed test blocks NEW ENTRIES only —
    # existing positions are always managed regardless.
    # Blackout-aware: if the event/research calendar blocks entries right now,
    # verification is DEFERRED into the management loop (which starts on time
    # so existing positions are never left unmanaged) — not spent and failed.
    import json as _json
    entries_blocked = False
    verified_file = PROJECT_ROOT / "data" / "verified_accounts.json"
    account_number = str(broker.account().account_number)
    try:
        verified = set(_json.loads(verified_file.read_text()))
    except Exception:
        verified = set()

    def blackout_until():
        """Latest no_entry_before across static calendar + today's research."""
        from datetime import time as dt_time
        from trader.events import effects_for, load_events
        nb = None
        try:
            effs = effects_for(datetime.now(ET).date(),
                               load_events(PROJECT_ROOT / "config" / "events.yaml"))
            nb = effs.get("no_entry_before")
            reff = _json.loads((PROJECT_ROOT / "data" / "research_effects.json").read_text())
            if reff.get("date") == datetime.now(ET).date().isoformat():
                rnb = reff["effects"].get("no_entry_before")
                if rnb:
                    t = dt_time.fromisoformat(rnb)
                    nb = max(nb, t) if nb else t
        except Exception as e:
            log(f"blackout check failed (treating as none): {e}")
        return nb

    def run_verification() -> bool:
        """Returns True if entries are allowed (passed or already verified)."""
        tg(f"🧪 First session on account {account_number}: running MLEG verification "
           "(1-lot open + close)...")
        r = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "test_mleg.py")],
                           capture_output=True, text=True, cwd=PROJECT_ROOT)
        out = (r.stdout + "\n" + r.stderr).strip()
        log(out)
        summary = [ln for ln in out.splitlines()
                   if not re.match(r'\s*(File |Traceback|raise |[A-Za-z.]*Error|requests\.|alpaca\.)', ln)
                   and ln.strip()]
        status = "✅ passed" if r.returncode == 0 else "❌ FAILED"
        tail = esc("\n".join(summary[-14:]))
        tg(f"MLEG verification {status}\n<code>{tail[-2800:]}</code>")
        if r.returncode == 0:
            verified.add(account_number)
            verified_file.parent.mkdir(exist_ok=True)
            verified_file.write_text(_json.dumps(sorted(verified)))
            return True
        tg("❌ MLEG verification failed — new entries blocked until it passes. "
           "Existing positions are still managed; will retry after any blackout.")
        return False

    verify_pending = False
    if os.environ.get("SKIP_MLEG_TEST"):
        tg("⏭️ MLEG verification skipped (env override).")
    elif account_number in verified and not os.environ.get("FORCE_MLEG_TEST"):
        tg(f"✅ Account {account_number} already MLEG-verified — skipping daily test.")
    else:
        nb = blackout_until()
        if nb and datetime.now(ET).time() < nb:
            verify_pending = True
            entries_blocked = True
            tg(f"⏳ Entry blackout until {nb:%H:%M} ET (event calendar) — verification "
               "and entries deferred; management runs meanwhile.")
        else:
            entries_blocked = not run_verification()

    # 3 ── entry attempts: at start, then periodically (recycle freed budget) ──
    def attempt_entry(quiet: bool = False):
        """Ladder -> dedup -> risk gates -> execute. Returns True if opened."""
        state = build_account_state(broker, journal)
        proposal = stack["strategy"].propose_core_ladder("XSP", "put")
        already = {(p["underlying"], p["expiry"], p["structure"])
                   for p in journal.open_positions()}
        if proposal and (proposal.underlying, proposal.expiry.isoformat(),
                         proposal.structure) in already:
            if not quiet:
                tg(f"ℹ️ Equivalent position already open ({proposal.underlying} "
                   f"{proposal.expiry}) — not doubling up.")
            return False
        if proposal is None:
            if not quiet:
                tg("ℹ️ No viable core entry right now.")
            return False
        decision = stack["risk"].evaluate(proposal, state)
        if decision.verdict != Verdict.APPROVED:
            return False   # veto path already alerts via risk agent
        pos_id = stack["execution"].execute(proposal, decision.adjusted_qty)
        if pos_id is None and not quiet:
            tg("⚠️ Core entry unfilled after re-pegs — continuing without it.")
        return pos_id is not None

    if entries_blocked:
        tg("⏭️ Entry step skipped (entries blocked) — going straight to management.")
    else:
        try:
            attempt_entry()
        except Exception as e:
            log(traceback.format_exc())
            tg(f"⚠️ Entry step error: {esc(e)} — continuing to management loop.")

    # 4 ── manage until close (+ periodic re-entry to redeploy freed budget) ──
    # FLATTEN_AT_ET (ISO, ET): competition wind-down — from this moment, no new
    # entries, flatten everything (retrying each cycle until flat), then send a
    # final report and exit. Used on deadline day: P&L is evaluated at the
    # submission deadline, so everything must be REALIZED before it.
    flatten_at = None
    if os.environ.get("FLATTEN_AT_ET"):
        flatten_at = datetime.fromisoformat(os.environ["FLATTEN_AT_ET"]).replace(tzinfo=ET)
        tg(f"🏁 Wind-down armed: full flatten at {flatten_at:%H:%M} ET.")

    tg("🔁 Management loop running (60s cycles until market close).")
    last_hb = time.time()
    last_entry_attempt = time.time()
    winding_down = False
    while True:
        try:
            clock = broker.clock()
            if not clock.is_open:
                break
            if flatten_at and datetime.now(ET) >= flatten_at:
                if not winding_down:
                    winding_down = True
                    entries_blocked = True
                    tg("🏁 <b>Competition wind-down</b> — flattening all positions now.")
                stack["execution"].flatten_all("competition wind-down")
                if not journal.open_positions():
                    state = build_account_state(broker, journal)
                    tg(f"🏁 <b>Book flat.</b> Final equity <b>${state.equity:,.2f}</b> "
                       f"— all P&amp;L realized ahead of the deadline. Standing down.")
                    break
                time.sleep(60)
                continue
            state = build_account_state(broker, journal)
            stack["risk"].observe_equity(datetime.now(ET), state.equity,
                                         state.pnl_today, valid=True)
            if stack["risk"].flatten_required:
                stack["execution"].flatten_all("drawdown kill switch")
            else:
                stack["execution"].manage_cycle(state.minutes_to_close)
                if verify_pending:
                    nb = blackout_until()
                    if nb is None or datetime.now(ET).time() >= nb:
                        verify_pending = False
                        entries_blocked = not run_verification()
                        if not entries_blocked:
                            attempt_entry()
                            last_entry_attempt = time.time()
                elif (not entries_blocked
                        and time.time() - last_entry_attempt >= ENTRY_RETRY_SECONDS):
                    last_entry_attempt = time.time()
                    attempt_entry(quiet=True)   # gates/dedup decide; journal records
            if time.time() - last_hb >= HEARTBEAT_SECONDS:
                last_hb = time.time()
                tg(f"💓 Equity <b>${state.equity:,.2f}</b> · day P&amp;L <b>${state.pnl_today:+,.2f}</b>\n"
                   f"Open positions {state.open_positions} · open risk ${state.open_risk_usd:,.0f}")
        except Exception as e:
            log(traceback.format_exc())
            tg(f"⚠️ Cycle error: {esc(e)} — retrying next cycle.")
        time.sleep(60)

    # 5 ── post-close sweep + EOD report ──────────────────────────────────
    for pos in journal.open_positions():
        if pos["expiry"] <= datetime.now(ET).date().isoformat():
            journal.close_position(pos["id"], status="expired")
            journal.log("note", "execution", {
                "msg": f"position {pos['id']} expired (cash settlement); "
                       f"reconcile realized P&L from account activity next session"})
    try:
        state = build_account_state(broker, journal)
        closes = journal.events_since(datetime.now(ET).strftime("%Y-%m-%d"), kind="close")
        realized = sum(e["payload"].get("pnl", 0) for e in closes)
        tg(f"🌅 <b>Session complete</b>\n\n"
           f"Equity <b>${state.equity:,.2f}</b> · day P&amp;L <b>${state.pnl_today:+,.2f}</b>\n"
           f"Trades closed: {len(closes)} · realized ${realized:+,.2f}\n"
           f"Open positions carried: {state.open_positions}\n\n"
           f"Runner exiting cleanly.")
    except Exception as e:
        tg(f"🌅 Session complete (report error: {esc(e)}). Runner exiting.")


if __name__ == "__main__":
    main()
