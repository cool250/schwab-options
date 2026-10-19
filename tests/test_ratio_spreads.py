"""Ratio-spread grouping of closed trades (service/portfolio/ratio_spreads.py)."""

import pytest

from service.portfolio.ratio_spreads import group_ratio_spreads
from tests.conftest import option_leg

OCT = ("2026-10-01", "2026-10-31")


def closed_trades(make_service, legs):
    return make_service(legs).get_option_transactions("", *OCT, "ALL", realized_gains_only=True)


def test_one_by_two_put_ratio_becomes_one_record_with_the_combined_pnl(make_service):
    trades = closed_trades(make_service, [
        # buy 1 x 700 put, sell 2 x 690 puts, opened together
        option_leg("2026-10-01", "OPENING", 1, 5.00, strike=700.0),
        option_leg("2026-10-01", "OPENING", -2, 3.00, strike=690.0),
        option_leg("2026-10-10", "CLOSING", -1, 1.00, strike=700.0),
        option_leg("2026-10-10", "CLOSING", 2, 0.50, strike=690.0),
    ])
    [spread] = group_ratio_spreads(trades)
    assert spread["strategy"] == "RATIO_SPREAD"
    assert spread["ratio"] == "1:2"
    # long: (1.00 - 5.00) x 100 = -400; short: (3.00 - 0.50) x 2 x 100 = +500
    assert spread["total_amount"] == pytest.approx(100.0)
    assert spread["total_amount"] == pytest.approx(sum(t["total_amount"] for t in trades))


def test_three_strikes_are_left_ungrouped(make_service):
    trades = closed_trades(make_service, [
        option_leg("2026-10-01", "OPENING", 1, 5.00, strike=700.0),
        option_leg("2026-10-01", "OPENING", -1, 3.00, strike=690.0),
        option_leg("2026-10-01", "OPENING", -1, 2.00, strike=680.0),
        option_leg("2026-10-10", "CLOSING", -1, 1.00, strike=700.0),
        option_leg("2026-10-10", "CLOSING", 1, 0.50, strike=690.0),
        option_leg("2026-10-10", "CLOSING", 1, 0.25, strike=680.0),
    ])
    grouped = group_ratio_spreads(trades)
    assert len(grouped) == 3
    assert not any(t.get("strategy") == "RATIO_SPREAD" for t in grouped)


def test_one_to_one_spread_is_not_a_ratio_spread(make_service):
    trades = closed_trades(make_service, [
        option_leg("2026-10-01", "OPENING", 1, 5.00, strike=700.0),
        option_leg("2026-10-01", "OPENING", -1, 3.00, strike=690.0),
        option_leg("2026-10-10", "CLOSING", -1, 1.00, strike=700.0),
        option_leg("2026-10-10", "CLOSING", 1, 0.50, strike=690.0),
    ])
    assert len(group_ratio_spreads(trades)) == 2
