"""Risk gate tests — every gate, the shrink logic, and the debounce layer."""

from datetime import date, datetime, timedelta, timezone

import pytest

from trader.agents.base import AccountState, TradeProposal, Verdict
from trader.agents.risk import RiskAgent
from trader.broker.sanity import check_equity_agreement, check_quote, check_underlying_jump

RISK_CFG = {
    "max_daily_loss_usd": 2000,
    "max_total_drawdown_usd": 5000,
    "max_open_risk_usd": 10000,
    "max_risk_per_trade_usd": 1500,
    "max_positions": 8,
    "max_contracts_per_order": 10,
    "no_new_risk_into_weekend": True,
    "trading_hours_only": True,
    "entry_buffer_open_minutes": 15,
    "entry_buffer_close_minutes": 30,
    "debounce": {
        "daily_loss": {"readings": 2, "min_span_seconds": 300},
        "position_stop": {"readings": 2, "min_span_seconds": 120},
        "drawdown_flatten": {"readings": 3, "min_span_seconds": 900},
    },
}

MONDAY = date(2026, 8, 31)
FRIDAY = date(2026, 8, 28)
T0 = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)


def agent():
    return RiskAgent(RISK_CFG, starting_equity=100_000)


def state(**kw) -> AccountState:
    base = dict(equity=100_000, pnl_today=0, open_risk_usd=0, open_positions=0,
                market_open=True, minutes_since_open=60, minutes_to_close=120,
                today=MONDAY, is_friday=False)
    base.update(kw)
    return AccountState(**base)


def proposal(**kw) -> TradeProposal:
    base = dict(underlying="XSP", structure="put_credit_spread", legs=[], qty=3,
                net_price=0.90, is_credit=True, max_loss_per_lot_usd=410,
                expiry=MONDAY, rationale="test")
    base.update(kw)
    return TradeProposal(**base)


# ── sizing gates ─────────────────────────────────────────────────────────

def test_clean_approval_full_size():
    d = agent().evaluate(proposal(), state())
    assert d.verdict == Verdict.APPROVED
    assert d.adjusted_qty == 3


def test_gate3_shrinks_to_per_trade_cap():
    # 10 lots * $410 = $4,100 > $1,500 cap -> floor(1500/410) = 3 lots
    d = agent().evaluate(proposal(qty=10), state())
    assert d.verdict == Verdict.APPROVED
    assert d.adjusted_qty == 3


def test_gate4_shrinks_to_remaining_budget():
    # $9,600 already deployed -> $400 left -> 0 lots of $410... veto
    d = agent().evaluate(proposal(qty=3), state(open_risk_usd=9600))
    assert d.verdict == Verdict.VETOED
    # $9,100 deployed -> $900 left -> 2 lots fit
    d = agent().evaluate(proposal(qty=3), state(open_risk_usd=9100))
    assert d.verdict == Verdict.APPROVED
    assert d.adjusted_qty == 2


def test_gate6_contracts_per_order_cap():
    d = agent().evaluate(proposal(qty=50, max_loss_per_lot_usd=100), state())
    assert d.verdict == Verdict.APPROVED
    assert d.adjusted_qty == 10   # min(50, floor(1500/100)=15, budget 100, cap 10)


def test_gate5_position_count():
    d = agent().evaluate(proposal(), state(open_positions=8))
    assert d.verdict == Verdict.VETOED


# ── weekend rule ─────────────────────────────────────────────────────────

def test_gate7_friday_multiday_vetoed_0dte_allowed():
    fri = state(today=FRIDAY, is_friday=True)
    assert agent().evaluate(proposal(expiry=MONDAY), fri).verdict == Verdict.VETOED
    assert agent().evaluate(proposal(expiry=FRIDAY), fri).verdict == Verdict.APPROVED


# ── market hours ─────────────────────────────────────────────────────────

def test_gate8_closed_and_buffers():
    assert agent().evaluate(proposal(), state(market_open=False)).verdict == Verdict.VETOED
    assert agent().evaluate(proposal(), state(minutes_since_open=5)).verdict == Verdict.VETOED
    assert agent().evaluate(proposal(), state(minutes_to_close=10)).verdict == Verdict.VETOED
    assert agent().evaluate(proposal(), state(minutes_since_open=15)).verdict == Verdict.APPROVED


# ── kill switches + debounce ─────────────────────────────────────────────

def test_gate1_needs_sustained_breach():
    a = agent()
    a.observe_equity(T0, 98_000, -2100, valid=True)
    assert a.evaluate(proposal(), state()).verdict == Verdict.APPROVED  # 1 reading: not yet
    a.observe_equity(T0 + timedelta(seconds=301), 98_000, -2100, valid=True)
    assert a.evaluate(proposal(), state()).verdict == Verdict.VETOED    # confirmed


def test_gate1_recovery_resets_counter():
    a = agent()
    a.observe_equity(T0, 98_000, -2100, valid=True)
    a.observe_equity(T0 + timedelta(seconds=301), 99_500, -500, valid=True)   # recovered
    a.observe_equity(T0 + timedelta(seconds=602), 98_000, -2100, valid=True)  # breach again
    assert a.evaluate(proposal(), state()).verdict == Verdict.APPROVED  # count restarted


def test_invalid_readings_pause_never_trigger():
    a = agent()
    for i in range(10):  # ten glitched readings in a row
        a.observe_equity(T0 + timedelta(seconds=60 * i), 0, -999_999, valid=False)
    assert a.evaluate(proposal(), state()).verdict == Verdict.APPROVED
    assert a.daily_kill.paused


def test_invalid_reading_does_not_reset_breach_count():
    a = agent()
    a.observe_equity(T0, 98_000, -2100, valid=True)
    a.observe_equity(T0 + timedelta(seconds=150), 0, 0, valid=False)          # glitch: pause
    a.observe_equity(T0 + timedelta(seconds=301), 98_000, -2100, valid=True)  # still breached
    assert a.evaluate(proposal(), state()).verdict == Verdict.VETOED


def test_gate2_flatten_needs_three_readings_over_15min():
    a = agent()
    a.observe_equity(T0, 94_900, -5100, valid=True)
    a.observe_equity(T0 + timedelta(seconds=450), 94_900, -5100, valid=True)
    assert not a.flatten_required                       # 2 readings, span < 900s
    a.observe_equity(T0 + timedelta(seconds=901), 94_900, -5100, valid=True)
    assert a.flatten_required
    assert a.evaluate(proposal(), state(equity=94_900)).verdict == Verdict.VETOED


def test_daily_reset_clears_gate1_not_gate2():
    a = agent()
    for s in (0, 301):
        a.observe_equity(T0 + timedelta(seconds=s), 98_000, -2100, valid=True)
    assert a.daily_kill.confirmed
    a.reset_daily()
    assert not a.daily_kill.confirmed


# ── data sanity ──────────────────────────────────────────────────────────

def test_quote_sanity():
    now = datetime.now(timezone.utc)
    assert check_quote(1.0, 1.1, now, now=now).ok
    assert not check_quote(0, 1.1, now, now=now).ok                        # no bid
    assert not check_quote(1.2, 1.1, now, now=now).ok                      # crossed
    assert not check_quote(0.5, 1.5, now, now=now).ok                      # thin book
    assert not check_quote(1.0, 1.1, now - timedelta(seconds=120), now=now).ok  # stale
    # low-priced near-expiry option: 5c spread is 59% of mid but absolutely tight
    assert check_quote(0.06, 0.11, now, now=now).ok


def test_underlying_jump_and_equity_agreement():
    assert check_underlying_jump(660, 661).ok
    assert not check_underlying_jump(660, 640).ok          # 3% in one interval
    assert check_underlying_jump(None, 660).ok             # first reading
    assert check_equity_agreement(100_000, 99_500).ok
    assert not check_equity_agreement(100_000, 98_500).ok


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
