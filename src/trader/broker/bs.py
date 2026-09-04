"""Black-Scholes fallback greeks — used when the data feed's greeks are absent.

Self-contained from the option chain itself:
  * spot: inferred from put-call parity at the strike where |call_mid - put_mid|
    is smallest (deepest liquidity, both sides near the money)
  * IV: solved from the option's own mid by bisection
  * delta: standard BS with r as configured (dividends ignored — fine at 0-5 DTE)
"""

import math

SQRT2 = math.sqrt(2.0)


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def bs_price(spot: float, strike: float, t_years: float, iv: float,
             r: float, is_call: bool) -> float:
    if t_years <= 0 or iv <= 0:
        intrinsic = (spot - strike) if is_call else (strike - spot)
        return max(0.0, intrinsic)
    d1 = (math.log(spot / strike) + (r + iv * iv / 2) * t_years) / (iv * math.sqrt(t_years))
    d2 = d1 - iv * math.sqrt(t_years)
    if is_call:
        return spot * _ncdf(d1) - strike * math.exp(-r * t_years) * _ncdf(d2)
    return strike * math.exp(-r * t_years) * _ncdf(-d2) - spot * _ncdf(-d1)


def bs_delta(spot: float, strike: float, t_years: float, iv: float,
             r: float, is_call: bool) -> float:
    if t_years <= 0 or iv <= 0:
        itm = spot > strike if is_call else spot < strike
        return (1.0 if itm else 0.0) * (1 if is_call else -1)
    d1 = (math.log(spot / strike) + (r + iv * iv / 2) * t_years) / (iv * math.sqrt(t_years))
    return _ncdf(d1) if is_call else _ncdf(d1) - 1.0


def implied_vol(price: float, spot: float, strike: float, t_years: float,
                r: float, is_call: bool, lo: float = 0.005, hi: float = 5.0) -> float | None:
    """Bisection solve; None if price is outside the no-arbitrage bracket."""
    if price <= 0 or t_years <= 0:
        return None
    if bs_price(spot, strike, t_years, lo, r, is_call) > price:
        return None
    if bs_price(spot, strike, t_years, hi, r, is_call) < price:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs_price(spot, strike, t_years, mid, r, is_call) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def spot_from_parity(pairs: list[tuple[float, float, float]], r: float,
                     t_years: float) -> float | None:
    """pairs: (strike, call_mid, put_mid). Parity: S = C - P + K*e^-rT.
    Uses the strike where |C - P| is smallest (nearest the money)."""
    if not pairs:
        return None
    k, c, p = min(pairs, key=lambda x: abs(x[1] - x[2]))
    return c - p + k * math.exp(-r * t_years)
