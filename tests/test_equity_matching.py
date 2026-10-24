"""Equity and outright-futures FIFO matching
(TransactionService.get_equity_transactions)."""

import pytest

from tests.conftest import equity_leg


def test_round_trip_realizes_the_difference(make_service):
    svc = make_service(equity_legs=[
        equity_leg("2026-09-01", "AAPL", 100, 100.0),
        equity_leg("2026-10-05", "AAPL", -100, 110.0),
    ])
    [trade] = svc.get_equity_transactions("", "2026-10-01", "2026-10-31", "ALL", realized_gains_only=True)
    assert trade["status"] == "CLOSED"
    assert trade["total_amount"] == pytest.approx(1000.0)


def test_partial_sale_closes_part_and_leaves_an_open_lot(make_service):
    svc = make_service(equity_legs=[
        equity_leg("2026-10-01", "AAPL", 100, 100.0),
        equity_leg("2026-10-05", "AAPL", -40, 110.0),
    ])
    rows = svc.get_equity_transactions("", "2026-10-01", "2026-10-31", "ALL", realized_gains_only=False)
    closed = [r for r in rows if r["status"] == "CLOSED"]
    still_open = [r for r in rows if r["status"] == "OPEN"]
    assert [r["quantity"] for r in closed] == [40]
    assert closed[0]["total_amount"] == pytest.approx(400.0)
    assert [r["quantity"] for r in still_open] == [60]


def test_fifo_closes_the_oldest_lot_first(make_service):
    svc = make_service(equity_legs=[
        equity_leg("2026-09-01", "AAPL", 10, 100.0),
        equity_leg("2026-09-15", "AAPL", 10, 120.0),
        equity_leg("2026-10-05", "AAPL", -10, 130.0),
    ])
    [trade] = svc.get_equity_transactions("", "2026-10-01", "2026-10-31", "ALL", realized_gains_only=True)
    assert trade["open_price"] == 100.0
    assert trade["total_amount"] == pytest.approx(300.0)


def test_short_futures_round_trip_by_root_symbol(make_service):
    svc = make_service(equity_legs=[
        equity_leg("2026-10-01", "/ESZ26:XCME", -1, 7700.0, asset_type="FUTURE", multiplier=50),
        equity_leg("2026-10-06", "/ESZ26:XCME", 1, 7650.0, asset_type="FUTURE", multiplier=50),
    ])
    [trade] = svc.get_equity_transactions("/ES", "2026-10-01", "2026-10-31", "FUTURE", realized_gains_only=True)
    assert trade["symbol"] == "ES"
    assert trade["total_amount"] == pytest.approx(2500.0)  # 50 points x $50, short


def test_close_without_its_open_in_the_window_is_not_realized(make_service):
    # The opening buy fell outside the lookback window: no cost basis, so
    # no realized P&L can be computed for it.
    svc = make_service(equity_legs=[equity_leg("2026-10-05", "AAPL", -100, 110.0)])
    assert svc.get_equity_transactions("", "2026-10-01", "2026-10-31", "ALL", realized_gains_only=True) == []


def test_sale_of_shares_bought_before_the_history_is_not_a_short(make_service):
    # Sold shares bought before the fetched history: the sale must not open a
    # phantom short that the next buy "closes" (pairing unrelated trades).
    svc = make_service(equity_legs=[
        {**equity_leg("2026-09-01", "CRM", -200, 250.0), "position_effect": "CLOSING"},
        {**equity_leg("2026-09-10", "CRM", 200, 240.0), "position_effect": "OPENING"},
        {**equity_leg("2026-10-05", "CRM", -200, 200.0), "position_effect": "CLOSING"},
    ])
    [trade] = svc.get_equity_transactions("", "2026-09-01", "2026-10-31", "ALL", realized_gains_only=True)
    assert (trade["date"], trade["close_date"]) == ("2026-09-10", "2026-10-05")
    assert trade["total_amount"] == pytest.approx(-8000.0)


def test_short_stock_covered_by_an_assignment(make_service):
    # Sold short, then a put assignment buys the shares back (tagged CLOSING).
    svc = make_service(equity_legs=[
        {**equity_leg("2026-04-10", "IWM", -300, 251.0), "position_effect": "OPENING"},
        {**equity_leg("2026-09-18", "IWM", 300, 290.0), "position_effect": "CLOSING"},
    ])
    [trade] = svc.get_equity_transactions("", "2026-09-01", "2026-09-30", "ALL", realized_gains_only=True)
    assert trade["total_amount"] == pytest.approx(-11700.0)


def test_lookback_is_not_shrunk_to_one_request(make_service):
    # A YTD range plus the full lookback is longer than one Schwab request;
    # the service asks for all of it (the provider splits the fetch).
    svc = make_service()
    seen = []
    svc.provider.fetch_equity_future_legs = lambda start, end: seen.append((start, end)) or []
    svc.get_equity_transactions("", "2026-01-01", "2026-10-23", "ALL", realized_gains_only=True)
    [(start, _)] = seen
    assert start <= "2025-01-01"


def test_cost_of_held_position_takes_the_newest_fills_in_its_direction():
    from service.portfolio.equity_matching import cost_of_held_position
    fills = [
        {"date": "2026-02-05", "amount": 1000, "price": 620.0},   # long, later sold
        {"date": "2026-04-14", "amount": -1000, "price": 610.0},  # closes the long
        {"date": "2026-04-28", "amount": -100, "price": 620.0},   # short from an assignment
        {"date": "2026-04-30", "amount": -1000, "price": 610.0},  # short from an assignment
    ]
    assert cost_of_held_position(fills, -1100) == pytest.approx((100 * 620 + 1000 * 610) / 1100)
    # Part of the oldest fill still needed: only that part counts.
    assert cost_of_held_position(fills, -1050) == pytest.approx((50 * 620 + 1000 * 610) / 1050)


def test_cost_of_held_position_is_none_when_history_falls_short():
    from service.portfolio.equity_matching import cost_of_held_position
    # Held 200, but only 100 bought within the history; a $0 transfer doesn't count.
    fills = [{"date": "2026-09-01", "amount": 100, "price": 300.0}, {"date": "2026-10-05", "amount": 90, "price": 0.0}]
    assert cost_of_held_position(fills, 200) is None
    assert cost_of_held_position([], -100) is None


def test_stock_fill_costs_per_symbol(make_service):
    svc = make_service(equity_legs=[
        equity_leg("2026-09-18", "IWM", 300, 290.0),
        equity_leg("2026-10-01", "/ESZ26:XCME", 1, 7700.0, asset_type="FUTURE", multiplier=50),
    ])
    assert svc.get_stock_fill_costs({"IWM": 300, "GOOG": 200}) == {"IWM": pytest.approx(290.0), "GOOG": None}
