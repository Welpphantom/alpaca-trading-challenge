"""Tests for pure strategy logic: OCC parsing, strike selection, event effects."""

from datetime import date, datetime, time

from trader.broker.options import ChainRow, parse_occ, pick_credit_spread
from trader.events import effects_for, entry_blocked

NOW = datetime(2026, 8, 26, 12, 0)


def row(strike, delta, bid, ask):
    return ChainRow(symbol=f"XSP260826P{int(strike*1000):08d}", strike=strike,
                    delta=delta, bid=bid, ask=ask, quote_ts=None)


def make_put_chain():
    # spot ~660; deltas increase toward the money
    return [
        row(640, -0.05, 0.10, 0.14),
        row(643, -0.08, 0.22, 0.26),
        row(648, -0.15, 0.86, 0.94),
        row(650, -0.19, 1.16, 1.24),
        row(653, -0.26, 1.76, 1.84),
        row(655, -0.32, 2.36, 2.44),
    ]


def test_parse_occ():
    m = parse_occ("XSP260904P00648000")
    assert m == {"root": "XSP", "expiry": date(2026, 9, 4), "type": "put", "strike": 648.0}
    m = parse_occ("SPXW260826C03000000")
    assert m["root"] == "SPXW" and m["type"] == "call" and m["strike"] == 3000.0


def test_pick_spread_targets_delta():
    short, long, credit = pick_credit_spread(
        make_put_chain(), side="put", target_delta=0.15, width=5.0)
    assert short.strike == 648 and long.strike == 643
    assert credit == round(0.90 - 0.24, 2)  # mid_short - mid_long


def test_pick_spread_skips_missing_wing_within_tolerance():
    chain = [r for r in make_put_chain() if r.strike != 643]
    # 648 (0.15Δ) has no 643 wing -> next candidate within default ±0.07 tolerance
    # is 650 (0.19Δ), which needs 645 (missing); 653 (0.26Δ) exceeds tolerance.
    assert pick_credit_spread(chain, side="put", target_delta=0.15, width=5.0) is None
    # with a wider tolerance the fallback chain works: 653/648
    short, long, _ = pick_credit_spread(
        chain, side="put", target_delta=0.15, width=5.0, delta_tolerance=0.15)
    assert (short.strike, long.strike) == (653, 648)


def test_pick_spread_never_drifts_past_tolerance():
    # only a 0.32Δ strike viable -> must refuse a 0.15Δ request
    chain = [row(655, -0.32, 2.36, 2.44), row(650, -0.19, 1.16, 1.24)]
    assert pick_credit_spread(chain, side="put", target_delta=0.15, width=5.0) is None


def test_pick_spread_rejects_tiny_credit():
    chain = [row(648, -0.15, 0.30, 0.34), row(643, -0.08, 0.22, 0.26)]  # credit 0.10 < 0.50
    assert pick_credit_spread(chain, side="put", target_delta=0.15, width=5.0) is None


def test_pick_spread_ignores_dead_quotes():
    chain = [row(648, -0.15, 0, 0), row(643, -0.08, 0.22, 0.26)]
    assert pick_credit_spread(chain, side="put", target_delta=0.15, width=5.0) is None


EVENTS = [
    {"date": date(2026, 9, 4), "name": "NFP", "time_et": "08:30",
     "effect": {"no_entry_before": "09:45", "delta_max": 0.10, "size_multiplier": 0.5}},
    {"date": date(2026, 9, 4), "name": "judging", "effect": {"size_multiplier": 0.75}},
]


def test_effects_merge_most_conservative():
    eff = effects_for(date(2026, 9, 4), EVENTS)
    assert eff["delta_max"] == 0.10
    assert eff["size_multiplier"] == 0.5          # min of 0.5, 0.75
    assert eff["no_entry_before"] == time(9, 45)
    assert effects_for(date(2026, 9, 3), EVENTS) == {"names": []}


def test_entry_blocked_window():
    eff = effects_for(date(2026, 9, 4), EVENTS)
    assert entry_blocked(datetime(2026, 9, 4, 9, 30), eff) is not None
    assert entry_blocked(datetime(2026, 9, 4, 9, 45), eff) is None


def test_scaled_credit_floor():
    from trader.broker.options import scaled_credit_floor
    assert abs(scaled_credit_floor(0.10, 0.15) - 0.10) < 1e-9      # 15Δ: unchanged
    assert abs(scaled_credit_floor(0.10, 0.10) - 0.0667) < 1e-3    # 10Δ: ~2/3
    assert scaled_credit_floor(0.10, 0.02) == 0.04                 # clamped at min
    # at 10Δ a $0.34 credit on $5 wings passes the ~$0.334 floor; old fixed
    # floor ($0.50) would have rejected it
    chain = [row(648, -0.10, 0.34, 0.38), row(643, -0.05, 0.01, 0.03)]
    floor = scaled_credit_floor(0.10, 0.10)
    picked = pick_credit_spread(chain, side="put", target_delta=0.10, width=5.0,
                                min_credit_frac=floor)
    assert picked is not None and picked[2] == 0.34
    assert pick_credit_spread(chain, side="put", target_delta=0.10,
                              width=5.0) is None  # default 0.10 floor rejects
