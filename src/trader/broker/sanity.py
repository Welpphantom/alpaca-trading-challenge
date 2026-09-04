"""Data-quality checks. A reading that fails any check is DISCARDED — it
counts neither for nor against kill switches, and no order may be priced
off it. Bad data always results in doing nothing.
"""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class QuoteCheck:
    ok: bool
    reason: str = ""


def check_quote(
    bid: float,
    ask: float,
    quote_ts: datetime,
    *,
    now: datetime | None = None,
    max_spread_pct_of_mid: float = 0.40,
    max_age_seconds: float = 60,
    spread_abs_ok: float = 0.10,
) -> QuoteCheck:
    now = now or datetime.now(timezone.utc)
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return QuoteCheck(False, f"missing/zero quote (bid={bid}, ask={ask})")
    if bid > ask:
        return QuoteCheck(False, f"crossed quote (bid {bid} > ask {ask})")
    mid = (bid + ask) / 2
    # Thin book = spread wide in BOTH relative and absolute terms. A 5-cent
    # spread on an $0.08 option is 60% of mid but perfectly normal (low-priced
    # options near expiry) — the absolute floor keeps those tradable.
    if (mid > 0 and (ask - bid) / mid > max_spread_pct_of_mid
            and (ask - bid) > spread_abs_ok):
        return QuoteCheck(False, f"thin book: spread {(ask - bid):.2f} > {max_spread_pct_of_mid:.0%} of mid {mid:.2f}")
    age = (now - quote_ts).total_seconds()
    if age > max_age_seconds:
        return QuoteCheck(False, f"stale quote ({age:.0f}s old)")
    return QuoteCheck(True)


def check_underlying_jump(
    prev_price: float | None, price: float, max_jump_pct: float = 0.02
) -> QuoteCheck:
    """A >max_jump_pct move since the previous reading is suspect until the
    next reading confirms it — real crashes persist, glitches don't."""
    if prev_price is None or prev_price <= 0:
        return QuoteCheck(True)
    jump = abs(price - prev_price) / prev_price
    if jump > max_jump_pct:
        return QuoteCheck(False, f"underlying jumped {jump:.1%} in one interval — awaiting confirmation")
    return QuoteCheck(True)


def check_equity_agreement(
    broker_equity: float, computed_equity: float, max_disagreement_usd: float = 1000
) -> QuoteCheck:
    diff = abs(broker_equity - computed_equity)
    if diff > max_disagreement_usd:
        return QuoteCheck(False, f"broker equity {broker_equity:,.0f} vs our marks {computed_equity:,.0f} disagree by ${diff:,.0f}")
    return QuoteCheck(True)
