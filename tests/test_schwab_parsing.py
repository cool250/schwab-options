"""How Schwab's records are classified (service/portfolio/providers/schwab.py).
Descriptions are the exact text Schwab uses."""

import pytest

from service.portfolio.providers.schwab import SchwabTransactionProvider

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
