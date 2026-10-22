"""Option trade matching: how opening and closing legs become realized P&L
(TransactionService.get_option_transactions)."""

import pytest

from tests.conftest import option_leg

OCT = ("2026-10-01", "2026-10-31")


def realized(service, ticker="", contract_type="ALL"):
    return service.get_option_transactions(ticker, *OCT, contract_type, realized_gains_only=True)


def test_short_put_bought_back_is_closed_with_premium_kept_minus_cost(make_service):
    svc = make_service([
        option_leg("2026-10-01", "OPENING", -1, 2.00),
        option_leg("2026-10-10", "CLOSING", 1, 0.50),
    ])
    [trade] = realized(svc)
    assert trade["type"] == "CLOSED"
    assert trade["total_amount"] == pytest.approx(150.0)  # (2.00 - 0.50) x 1 x 100
    assert trade["close_date"] == "2026-10-10"


def test_expired_option_keeps_the_whole_premium(make_service):
    svc = make_service([
        option_leg("2026-10-01", "OPENING", -1, 2.00),
        option_leg("2026-10-23", "CLOSING", 1, 0.00, close_event="EXPIRATION"),
    ])
    [trade] = realized(svc)
    assert trade["type"] == "EXPIRED"
    assert trade["total_amount"] == pytest.approx(200.0)


def test_exercised_futures_option_keeps_its_premium(make_service):
    # Schwab books the future at the strike, so the premium is the option's
    # whole contribution — zeroing it (like an equity assignment) would drop it.
    svc = make_service([
        option_leg("2026-10-01", "OPENING", -1, 20.0, underlying="ES", strike=7600.0),
        option_leg("2026-10-23", "CLOSING", 1, 0.0, underlying="ES", strike=7600.0, close_event="EXERCISE"),
    ])
    [trade] = realized(svc)
    assert trade["type"] == "EXERCISED"
    assert trade["total_amount"] == pytest.approx(1000.0)  # 20 x 1 x $50


def test_assigned_equity_option_is_left_out_of_realized_pnl(make_service):
    legs = [
        option_leg("2026-10-01", "OPENING", -1, 2.00),
        option_leg("2026-10-23", "CLOSING", 1, 0.00, close_event="ASSIGNMENT"),
    ]
    assert realized(make_service(legs)) == []
    # Including assignments, it shows as ASSIGNED with its P&L zeroed (the
    # premium is part of the assigned shares' cost basis instead).
    [trade] = make_service(legs).get_option_transactions("", *OCT, "ALL", realized_gains_only=False)
    assert trade["type"] == "ASSIGNED"
    assert trade["total_amount"] == 0


def test_open_leg_is_not_realized_but_is_returned_as_unrealized(make_service):
    legs = [option_leg("2026-10-05", "OPENING", -1, 2.00)]
    assert realized(make_service(legs)) == []
    [open_leg] = make_service(legs).get_option_transactions("", *OCT, "ALL", realized_gains_only=False, unrealized_only=True)
    assert open_leg["type"] == "TRADE"
    assert open_leg["total_amount"] == pytest.approx(200.0)  # entry credit, not a gain


def test_partial_close_realizes_the_closed_part_and_leaves_the_rest_open(make_service):
    legs = [
        option_leg("2026-10-01", "OPENING", -2, 2.00),
        option_leg("2026-10-10", "CLOSING", 1, 0.50),
    ]
    [closed] = realized(make_service(legs))
    assert closed["amount"] == 1
    assert closed["total_amount"] == pytest.approx(150.0)
    [still_open] = make_service(legs).get_option_transactions("", *OCT, "ALL", realized_gains_only=False, unrealized_only=True)
    assert still_open["amount"] == -1


def test_same_day_split_fills_are_combined_at_their_weighted_price(make_service):
    svc = make_service([
        option_leg("2026-10-01", "OPENING", -1, 2.00),
        option_leg("2026-10-01", "OPENING", -1, 3.00),
        option_leg("2026-10-10", "CLOSING", 2, 1.00),
    ])
    [trade] = realized(svc)
    assert trade["open_price"] == pytest.approx(2.50)
    assert trade["total_amount"] == pytest.approx(300.0)  # (2.50 - 1.00) x 2 x 100


def test_only_trades_closed_in_the_range_are_returned(make_service):
    svc = make_service([
        option_leg("2026-09-20", "OPENING", -1, 2.00, expiration="2026-09-26"),
        option_leg("2026-09-25", "CLOSING", 1, 0.50, expiration="2026-09-26"),
    ])
    assert realized(svc) == []


def test_futures_ticker_filter_accepts_the_leading_slash(make_service):
    legs = [
        option_leg("2026-10-01", "OPENING", -1, 20.0, underlying="ES", strike=7600.0),
        option_leg("2026-10-10", "CLOSING", 1, 5.0, underlying="ES", strike=7600.0),
        option_leg("2026-10-01", "OPENING", -1, 2.00),
        option_leg("2026-10-10", "CLOSING", 1, 0.50),
    ]
    assert [t["underlying_symbol"] for t in realized(make_service(legs), ticker="/ES")] == ["ES"]
    assert [t["underlying_symbol"] for t in realized(make_service(legs), ticker="ES")] == ["ES"]


def test_contract_type_filter(make_service):
    legs = [
        option_leg("2026-10-01", "OPENING", -1, 2.00, option_type="CALL", strike=720.0),
        option_leg("2026-10-10", "CLOSING", 1, 0.50, option_type="CALL", strike=720.0),
        option_leg("2026-10-01", "OPENING", -1, 2.00),
        option_leg("2026-10-10", "CLOSING", 1, 0.50),
    ]
    assert [t["option_type"] for t in realized(make_service(legs), contract_type="CALL")] == ["CALL"]


def test_open_futures_options_window_covers_an_evening_fill():
    # Schwab's endDate is 00:00 UTC of the date sent. Tomorrow's midnight UTC
    # is still this evening in the US, so an after-hours futures fill placed
    # later than that was dropped from Positions; the window must reach the
    # day after tomorrow.
    from datetime import timedelta

    from service.portfolio import TransactionService
    from tests.conftest import FakeTransactions
    from utils.market_time import market_today

    seen = {}

    class Recording(FakeTransactions):
        def fetch_option_legs(self, start_date, end_date):
            seen["end"] = end_date
            return []

    TransactionService(provider=Recording()).get_open_futures_options(lookback_days=30)
    assert seen["end"] >= (market_today() + timedelta(days=2)).strftime("%Y-%m-%d")
