"""Trades the account holder placed (TransactionService.get_placed_trades) —
the Reports page's Trade Details tab."""

from service.portfolio import TransactionService
from tests.conftest import FakeTransactions


def execution(date, placed=True, asset_class="OPTION", time=None):
    return {"date": date, "time": time, "order_id": "1" if placed else None, "placed": placed,
            "asset_class": asset_class, "position_effect": "OPENING"}


def test_only_placed_trades_in_the_range_are_returned_oldest_first():
    svc = TransactionService(provider=FakeTransactions(executions=[
        execution("2026-09-30", time="2026-09-30T15:00:00+00:00"),
        execution("2026-09-02"),
        execution("2026-09-30", time="2026-09-30T14:00:00+00:00"),
        execution("2026-09-15", placed=False),          # an expiration or assignment
        execution("2026-09-16", asset_class="FUND"),   # a money-market sweep
        execution("2026-10-01"),                        # after the range
    ]))
    result = svc.get_placed_trades("2026-09-01", "2026-09-30")
    assert [(t["date"], t["time"]) for t in result["trades"]] == [
        ("2026-09-02", None), ("2026-09-30", "2026-09-30T14:00:00+00:00"), ("2026-09-30", "2026-09-30T15:00:00+00:00"),
    ]
    assert result["not_placed"] == 1
