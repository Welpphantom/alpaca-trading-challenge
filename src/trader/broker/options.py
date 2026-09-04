"""Options chain access and multi-leg (MLEG) order construction.

Convention notes (from participant reports, to be verified by our own
scripts/test_mleg.py run before we trade on them):
  * SPX options list under the SPXW trading class; query with
    underlying_symbols=SPX. XSP (1/10th SPX, cash-settled) also available.
  * MLEG limit_price is SIGNED: negative = net credit, positive = net debit.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

from alpaca.trading.enums import (
    ContractType,
    OrderClass,
    OrderSide,
    PositionIntent,
    TimeInForce,
)
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    LimitOrderRequest,
    OptionLegRequest,
)

from trader.broker.alpaca_client import Broker


@dataclass(frozen=True)
class Leg:
    symbol: str          # OCC option symbol, e.g. XSP260904C00580000
    side: OrderSide      # BUY / SELL
    ratio: int = 1


OCC_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def scaled_credit_floor(base_frac: float, target_delta: float,
                        ref_delta: float = 0.15, min_frac: float = 0.04) -> float:
    """Delta-scaled minimum-credit fraction.

    The base floor (e.g. 10% of width) is calibrated for ref_delta (15Δ)
    spreads. Fair credit falls roughly in proportion to delta, so a fixed
    floor silently rejects ALL correctly-priced trades at tighter delta caps
    (observed live: three sessions of event-capped 10-12Δ days produced zero
    entries). Scaling keeps the same credit-per-unit-of-probability bar.
    """
    return max(min_frac, base_frac * (target_delta / ref_delta))


def parse_occ(symbol: str) -> dict:
    """XSP260904P00648000 -> {root, expiry, type, strike}"""
    m = OCC_RE.match(symbol)
    if not m:
        raise ValueError(f"not an OCC option symbol: {symbol}")
    root, ymd, cp, strike = m.groups()
    return {
        "root": root,
        "expiry": datetime.strptime(ymd, "%y%m%d").date(),
        "type": "call" if cp == "C" else "put",
        "strike": int(strike) / 1000.0,
    }


@dataclass(frozen=True)
class ChainRow:
    """One contract from a chain snapshot, normalized for strike selection."""
    symbol: str
    strike: float
    delta: float | None
    bid: float
    ask: float
    quote_ts: datetime | None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def pick_credit_spread(
    rows: list[ChainRow],
    *,
    side: str,                 # "put" | "call"
    target_delta: float,       # positive magnitude, e.g. 0.15
    width: float,              # strike distance, e.g. 5.0
    min_credit_frac: float = 0.10,   # credit must be >= this fraction of width
    delta_tolerance: float = 0.07,   # never drift further than this from target
) -> tuple[ChainRow, ChainRow, float] | None:
    """Pick (short, long, net_credit) from same-expiry rows of one type.

    Short strike: |delta| closest to target, within target +/- delta_tolerance,
    quote present. Long strike: `width` further OTM (exact strike match).
    Returns None when no viable pair exists — callers treat that as 'no trade'.
    A missing 12-18 delta strike must mean NO TRADE, never a 30-delta trade.
    """
    by_strike = {r.strike: r for r in rows}
    candidates = [
        r for r in rows
        if r.delta is not None
        and abs(abs(r.delta) - target_delta) <= delta_tolerance
        and abs(r.delta) >= 0.05
        and r.bid > 0 and r.ask > r.bid
    ]
    if not candidates:
        return None
    for short in sorted(candidates, key=lambda r: abs(abs(r.delta) - target_delta)):
        long_strike = short.strike - width if side == "put" else short.strike + width
        long = by_strike.get(round(long_strike, 3))
        if long is None or long.bid <= 0 or long.ask <= long.bid:
            continue
        credit = round(short.mid - long.mid, 2)
        if credit >= min_credit_frac * width:
            return short, long, credit
    return None


def fetch_chain(
    broker: Broker,
    underlying: str,
    expiration: date | None = None,
    expiration_lte: date | None = None,
    contract_type: ContractType | None = None,
    strike_gte: float | None = None,
    strike_lte: float | None = None,
    limit: int = 500,
):
    """Fetch option contracts for an underlying from the trading API."""
    req = GetOptionContractsRequest(
        underlying_symbols=[underlying],
        expiration_date=expiration,
        expiration_date_lte=expiration_lte,
        type=contract_type,
        strike_price_gte=str(strike_gte) if strike_gte is not None else None,
        strike_price_lte=str(strike_lte) if strike_lte is not None else None,
        limit=limit,
    )
    return broker.trading.get_option_contracts(req)


def build_mleg_limit_order(
    legs: list[Leg],
    qty: int,
    net_price: float,
    *,
    is_credit: bool,
    closing: bool = False,
) -> LimitOrderRequest:
    """Build a multi-leg limit order.

    `net_price` is passed as a positive number; `is_credit` controls the sign
    per the MLEG convention (negative limit_price = net credit). Keeping the
    sign logic in one place so no caller ever abs()'s or re-signs it.

    `closing` flips position_intent to *_TO_CLOSE — Alpaca rejects an order
    whose stated intent mismatches the actual position (verified live 8/26).
    """
    if net_price <= 0:
        raise ValueError("net_price must be positive; use is_credit for direction")
    limit_price = -net_price if is_credit else net_price

    def intent(side: OrderSide) -> PositionIntent:
        if closing:
            return (PositionIntent.BUY_TO_CLOSE if side == OrderSide.BUY
                    else PositionIntent.SELL_TO_CLOSE)
        return (PositionIntent.SELL_TO_OPEN if side == OrderSide.SELL
                else PositionIntent.BUY_TO_OPEN)

    return LimitOrderRequest(
        qty=qty,
        order_class=OrderClass.MLEG,
        time_in_force=TimeInForce.DAY,
        limit_price=limit_price,
        legs=[
            OptionLegRequest(
                symbol=leg.symbol,
                side=leg.side,
                ratio_qty=leg.ratio,
                position_intent=intent(leg.side),
            )
            for leg in legs
        ],
    )
