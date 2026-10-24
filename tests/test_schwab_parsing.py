"""How Schwab's records are classified (service/portfolio/providers/schwab.py).
Descriptions are the exact text Schwab uses."""

import pytest

from service.portfolio.providers.schwab import SchwabTransactionProvider
from utils.utils import get_date_object

classify = SchwabTransactionProvider._identify_close_event


@pytest.mark.parametrize("raw_type, description, expected", [
    # Equity options: closes arrive as RECEIVE_AND_DELIVER
    ("RECEIVE_AND_DELIVER", "Removed due to Expiration PUT ISHR RUSSELL 2000 $245 EXP 04/02/26", "EXPIRATION"),
    ("RECEIVE_AND_DELIVER", "Removed due to Assignment CALL INVESCO QQQ TR $610 EXP 04/13/26", "ASSIGNMENT"),
    ("RECEIVE_AND_DELIVER", "Removed due to Exercise PUT AIRBNB INC $126 EXP 11/07/25", "ASSIGNMENT"),
    # Futures options: closes arrive as ordinary TRADEs at $0
    ("TRADE", "Exercise, future settle 2.0 of /NQZ26 XCME 20 16 Oct 2026 29500.0 PUT", "EXERCISE"),
    ("TRADE", "Removal of option due to expiration of /ESZ26 XCME 50 16 Oct 2026 7650.0 PUT", "EXPIRATION"),
    # A normal trade is not a close event
    ("TRADE", None, None),
    ("TRADE", "Sell to open", None),
])
def test_close_event_classification(raw_type, description, expected):
    assert classify(raw_type, description, "SYM") == expected


@pytest.mark.parametrize("symbol, root", [
    ("/ESU26:XCME", "ES"),
    ("/NQU26:XCME", "NQ"),
    (".QN4M26:XCME", "NQ"),
    (".E3DM26_P7050:XCME", "ES"),
    ("AAPL", "AAPL"),
])
def test_futures_root_normalization(symbol, root):
    provider = SchwabTransactionProvider(client=object())  # no network
    assert provider.normalize_futures_symbol(symbol) == root


def _activity(activity_id, date, symbol, asset_type, amount, price, effect):
    from types import SimpleNamespace
    item = SimpleNamespace(
        instrument=SimpleNamespace(symbol=symbol, assetType=asset_type),
        amount=amount, price=price, cost=-amount * price, positionEffect=effect,
    )
    return SimpleNamespace(activityId=activity_id, tradeDate=get_date_object(date), transferItems=[item])


class _FakeClient:
    """Serves fixed records, recording each requested window."""

    def __init__(self, records):
        self.records, self.windows = records, []

    def fetch_transactions(self, start_date, end_date):
        self.windows.append((start_date, end_date))
        start, end = get_date_object(start_date), get_date_object(end_date)
        return [r for r in self.records if start <= r.tradeDate <= end]


def test_etf_fills_count_as_equity():
    client = _FakeClient([_activity(1, "2026-09-18", "IWM", "COLLECTIVE_INVESTMENT", 300.0, 290.0, "CLOSING")])
    [leg] = SchwabTransactionProvider(client=client).fetch_equity_future_legs("2026-09-01", "2026-09-30")
    assert (leg["symbol"], leg["asset_type"], leg["position_effect"]) == ("IWM", "EQUITY", "CLOSING")


def test_long_range_is_fetched_a_year_at_a_time_without_duplicates():
    # Record 2 sits on the boundary date, so both windows return it.
    client = _FakeClient([
        _activity(1, "2025-02-01", "CRM", "EQUITY", 200.0, 250.0, "OPENING"),
        _activity(2, "2026-01-01", "CRM", "EQUITY", 100.0, 240.0, "OPENING"),
        _activity(3, "2026-09-08", "CRM", "EQUITY", -200.0, 200.0, "CLOSING"),
    ])
    legs = SchwabTransactionProvider(client=client).fetch_equity_future_legs("2025-01-02", "2026-10-23")
    assert len(client.windows) == 2
    assert all((get_date_object(e) - get_date_object(s)).days <= 364 for s, e in client.windows)
    assert [leg["date"] for leg in legs] == ["2025-02-01", "2026-01-01", "2026-09-08"]
