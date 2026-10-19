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
