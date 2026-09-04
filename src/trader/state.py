"""Account-state snapshot: one call per cycle, feeds the risk gates."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from alpaca.trading.requests import GetCalendarRequest

from trader.agents.base import AccountState
from trader.broker.alpaca_client import Broker

ET = ZoneInfo("America/New_York")


def build_account_state(broker: Broker, journal) -> AccountState:
    acct = broker.account()
    clock = broker.clock()
    now_et = datetime.now(ET)
    today = now_et.date()

    minutes_since_open = 0.0
    minutes_to_close = 0.0
    if clock.is_open:
        cal = broker.trading.get_calendar(
            GetCalendarRequest(start=today, end=today))
        if cal:
            session_open = cal[0].open.replace(tzinfo=ET)
            minutes_since_open = (now_et - session_open).total_seconds() / 60
        minutes_to_close = (clock.next_close - now_et.astimezone(clock.next_close.tzinfo)
                            ).total_seconds() / 60

    equity = float(acct.equity)
    last_equity = float(acct.last_equity)
    return AccountState(
        equity=equity,
        pnl_today=equity - last_equity,
        open_risk_usd=journal.open_risk_usd(),
        open_positions=journal.open_position_count(),
        market_open=bool(clock.is_open),
        minutes_since_open=minutes_since_open,
        minutes_to_close=minutes_to_close,
        today=today,
        is_friday=today.weekday() == 4,
    )
