"""Live prices and unrealized P&L on the copilot's futures tools
(copilot/tools.py) — the same cases as the Positions page's
frontend/src/utils/positionPl.test.js, so the two can't drift apart."""

import pytest

from copilot.tools import futures_option_contracts, with_futures_marks, with_futures_option_marks


def test_a_short_futures_option_gains_what_it_lost_in_value():
    # Sold 2 NQ puts at 136 ($20/pt): entry value +5,440; now bid 100.
    [row] = with_futures_option_marks([{"symbol": "Q", "quantity": -2, "multiplier": 20, "total_value": 5440}], {"Q": 100})
    assert row["current_price"] == 100
    assert row["unrealized_pl"] == 5440 - 100 * 2 * 20


def test_a_ratio_spread_is_priced_leg_by_leg():
    # Long 1 at 30, short 2 at 20 ($50/pt): entry value (2*20 - 30) * 50 = 500.
    spread = {"multiplier": 50, "total_value": 500, "long_leg": {"symbol": "L", "amount": 1}, "short_leg": {"symbol": "S", "amount": 2}}
    [row] = with_futures_option_marks([dict(spread)], {"L": 10, "S": 4})
    assert row["current_price"] == 2 * 4 - 10
    assert row["unrealized_pl"] == 500 - (2 * 4 - 10) * 50
    [unpriced] = with_futures_option_marks([dict(spread)], {"L": 10})
    assert unpriced["current_price"] is None and unpriced["unrealized_pl"] is None


@pytest.mark.parametrize("symbol, quantity, entry, price, pl", [
    ("ES", 2, 7700, 7650, -50 * 2 * 50),
    ("NQ", -1, 29000, 28900, 100 * 20),
    ("/ES", 1, 7700, 7710, 10 * 50),
])
def test_an_outright_future_is_price_minus_entry_times_quantity_times_point_value(symbol, quantity, entry, price, pl):
    [row] = with_futures_marks([{"symbol": symbol, "quantity": quantity, "trade_price": entry}], {symbol: price})
    assert row["unrealized_pl"] == pl


def test_each_lot_is_priced_at_its_own_entry():
    row = {"symbol": "NQ", "quantity": 3, "trade_price": 29_000,
           "lots": [{"date": "2026-10-20", "quantity": 1, "trade_price": 29_400},
                    {"date": "2026-10-30", "quantity": 2, "trade_price": 28_800}]}
    [priced] = with_futures_marks([row], {"NQ": 28_900})
    assert priced["unrealized_pl"] == (28_900 - 29_000) * 3 * 20
    assert [lot["unrealized_pl"] for lot in priced["lots"]] == [(28_900 - 29_400) * 20, (28_900 - 28_800) * 2 * 20]


def test_an_unpriced_future_keeps_none():
    [row] = with_futures_marks([{"symbol": "ES", "quantity": 1, "trade_price": 7700}], {})
    assert row["current_price"] is None and row["unrealized_pl"] is None


def test_quote_requests_cover_both_legs_of_a_spread():
    contracts = futures_option_contracts(
        [{"ticker": "ES", "expiration_date": "2026-10-30", "long_leg": {"symbol": "L", "strike_price": 7700}, "short_leg": {"symbol": "S", "strike_price": 7600}}],
        [{"ticker": "NQ", "expiration_date": "2026-10-30", "symbol": "C", "strike_price": 29500}],
    )
    assert [(c["key"], c["underlying"], c["type"]) for c in contracts] == [("L", "/ES", "PUT"), ("S", "/ES", "PUT"), ("C", "/NQ", "CALL")]
