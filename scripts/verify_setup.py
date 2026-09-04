"""Sanity-check the whole pipeline. Run after filling .env:

    .venv/bin/python scripts/verify_setup.py

Checks: Alpaca auth, account + options approval level, market clock,
SPX/SPXW + XSP option chains, live option quote, Telegram delivery,
Anthropic key presence. Each check is independent — one failure doesn't
hide the rest.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trader.config import load_secrets, load_settings  # noqa: E402

PASS, FAIL, SKIP = "✅", "❌", "⏭️"
results: list[tuple[str, str, str]] = []


def check(name):
    def deco(fn):
        def run(*args, **kwargs):
            try:
                detail = fn(*args, **kwargs)
                results.append((PASS, name, detail or ""))
                return True
            except Exception as e:
                results.append((FAIL, name, f"{type(e).__name__}: {e}"))
                return False
        return run
    return deco


def main():
    secrets = load_secrets()
    load_settings()  # validates yaml parses

    if not (secrets.alpaca_api_key and secrets.alpaca_secret_key):
        print(f"{FAIL} ALPACA_API_KEY / ALPACA_SECRET_KEY missing in .env — fill those first.")
        sys.exit(1)

    from trader.broker.alpaca_client import Broker
    from trader.broker.options import fetch_chain

    broker = Broker(secrets)

    @check("Alpaca auth + account")
    def account_check():
        acct = broker.account()
        lvl = getattr(acct, "options_approved_level", None)
        return (f"account {acct.account_number} · equity ${float(acct.equity):,.0f} · "
                f"options level {lvl} (need >= 3 for spreads)")

    @check("Market clock")
    def clock_check():
        c = broker.clock()
        state = "OPEN" if c.is_open else "closed"
        return f"market {state} · next open {c.next_open} · next close {c.next_close}"

    @check("SPX (SPXW) option chain")
    def spx_chain():
        resp = fetch_chain(broker, "SPX", expiration_lte=date.today() + timedelta(days=7), limit=50)
        contracts = resp.option_contracts or []
        if not contracts:
            raise RuntimeError("no SPX contracts returned")
        c0 = contracts[0]
        return f"{len(contracts)} contracts <=7 DTE · e.g. {c0.symbol} exp {c0.expiration_date}"

    @check("XSP option chain")
    def xsp_chain():
        resp = fetch_chain(broker, "XSP", expiration_lte=date.today() + timedelta(days=7), limit=50)
        contracts = resp.option_contracts or []
        if not contracts:
            raise RuntimeError("no XSP contracts returned")
        return f"{len(contracts)} contracts <=7 DTE · e.g. {contracts[0].symbol}"

    @check("Live option quote (SPY chain)")
    def option_quote():
        from alpaca.data.requests import OptionLatestQuoteRequest

        resp = fetch_chain(broker, "SPY", expiration_lte=date.today() + timedelta(days=7), limit=5)
        contracts = resp.option_contracts or []
        if not contracts:
            raise RuntimeError("no SPY contracts returned")
        sym = contracts[0].symbol
        q = broker.option_data.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=sym)
        )[sym]
        return f"{sym} bid {q.bid_price} / ask {q.ask_price}"

    account_check()
    clock_check()
    spx_chain()
    xsp_chain()
    option_quote()

    if secrets.telegram_bot_token and secrets.telegram_chat_id:
        @check("Telegram delivery")
        def tg_check():
            from trader.notify.telegram import Telegram
            Telegram(secrets).send("✅ Alpaca trading agent: setup verification ping.")
            return "message sent — check your Telegram"
        tg_check()
    else:
        results.append((SKIP, "Telegram delivery", "TELEGRAM_* not set yet"))

    if secrets.anthropic_api_key:
        results.append((PASS, "Anthropic key", "present (not exercised here)"))
    else:
        results.append((SKIP, "Anthropic key", "ANTHROPIC_API_KEY not set yet"))

    print("\n=== Setup verification ===")
    for icon, name, detail in results:
        print(f"{icon} {name:<28} {detail}")
    failures = sum(1 for r in results if r[0] == FAIL)
    print(f"\n{len(results) - failures}/{len(results)} checks passing")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
