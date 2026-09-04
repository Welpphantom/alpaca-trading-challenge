"""Black-Scholes fallback sanity: round-trips and known relationships."""

import math

from trader.broker.bs import bs_delta, bs_price, implied_vol, spot_from_parity

SPOT, R = 660.0, 0.04
T_1D = 1 / 365.25


def test_iv_round_trip():
    for strike, is_call in [(648, False), (655, False), (665, True), (672, True)]:
        price = bs_price(SPOT, strike, T_1D, 0.18, R, is_call)
        iv = implied_vol(price, SPOT, strike, T_1D, R, is_call)
        assert iv is not None and abs(iv - 0.18) < 1e-4


def test_delta_signs_and_magnitudes():
    assert bs_delta(SPOT, 660, T_1D, 0.18, R, is_call=True) ==.5 or \
           abs(bs_delta(SPOT, 660, T_1D, 0.18, R, is_call=True) - 0.5) < 0.05  # ATM call ~0.5
    otm_put = bs_delta(SPOT, 648, T_1D, 0.18, R, is_call=False)
    assert -0.35 < otm_put < -0.02        # OTM put: small negative
    deep_put = bs_delta(SPOT, 600, T_1D, 0.18, R, is_call=False)
    assert -0.01 < deep_put <= 0          # far OTM: ~0


def test_put_call_parity_spot_recovery():
    pairs = []
    for k in (650, 655, 660, 665, 670):
        c = bs_price(SPOT, k, T_1D, 0.18, R, True)
        p = bs_price(SPOT, k, T_1D, 0.18, R, False)
        pairs.append((k, c, p))
    s = spot_from_parity(pairs, R, T_1D)
    assert abs(s - SPOT) < 0.01


def test_iv_rejects_unpriceable():
    assert implied_vol(0.0, SPOT, 648, T_1D, R, False) is None
    assert implied_vol(100.0, SPOT, 648, T_1D, R, False) is None  # above bracket
