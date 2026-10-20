"""PositionService pricing (service/portfolio/positions.py)."""

import pytest

from service.portfolio import PositionService


class FakePositions:
    """A PositionProvider with one short put and one stock; quotes as given."""

    def __init__(self, quotes):
        self.quotes = quotes

    def get_account_snapshot(self):
        base = {"tax_lot_long_price": None, "tax_lot_short_price": None, "long_open_pl": None, "short_open_pl": None}
        return {
            "balances": {"margin_balance": 0.0, "cash_balance": 1000.0, "mutual_fund_value": 0.0, "liquidation_value": 1000.0},
            "positions": [
                {**base, "asset_type": "OPTION", "symbol": "SPY   261023P00700000", "long_quantity": 0, "short_quantity": 1,
                 "average_price": 2.00, "underlying_symbol": "SPY", "strike_price": 700.0,
                 "expiration_date": "2026-10-23", "option_type": "P"},
                {**base, "asset_type": "EQUITY", "symbol": "AAPL", "long_quantity": 10, "short_quantity": 0,
                 "average_price": 100.0, "underlying_symbol": None, "strike_price": None,
                 "expiration_date": None, "option_type": None},
            ],
        }

    def get_quotes(self, symbols):
        return {s: self.quotes[s] for s in symbols if s in self.quotes}

    def list_accounts(self):
        return []


def test_short_put_pnl_is_premium_minus_current_value():
    [put], _ = PositionService(provider=FakePositions({"SPY   261023P00700000": 0.50})).get_option_position()
    assert put.total_value == pytest.approx(150.0)  # (2.00 - 0.50) x 100


def test_missing_quote_leaves_pnl_unknown_instead_of_the_whole_premium():
    [put], _ = PositionService(provider=FakePositions({})).get_option_position()
    assert put.current_price is None
    assert put.total_value is None  # not +$200 (the whole premium)


def test_missing_stock_quote_is_unknown_not_zero():
    [stock] = PositionService(provider=FakePositions({})).get_stock_position()
    assert stock.current_price is None


def test_positions_are_numbers_not_display_strings():
    svc = PositionService(provider=FakePositions({"SPY   261023P00700000": 0.50, "AAPL": 110.0}))
    [put], _ = svc.get_option_position()
    assert (put.strike_price, put.quantity, put.trade_price, put.current_price) == (700.0, -1, 2.00, 0.50)
    assert put.days_to_expiry is not None
    [stock] = svc.get_stock_position()
    assert (stock.quantity, stock.trade_price, stock.current_price) == (10, 100.0, 110.0)
    balances = svc.get_balances()
    assert (balances.cash_balance, balances.mutual_fund_value, balances.account_value) == (1000.0, 0.0, 1000.0)


def _set_properties(monkeypatch, tmp_path, text):
    """Point utils/app_config at a properties file for this test only."""
    from utils import app_config

    path = tmp_path / "app.properties"
    path.write_text(text)
    monkeypatch.setenv("APP_PROPERTIES", str(path))
    app_config.reload_config()


@pytest.fixture(autouse=True)
def _restore_app_config():
    from utils import app_config

    yield
    app_config.reload_config()


def test_open_futures_ratio_spread_is_one_typed_row_with_both_legs(monkeypatch, tmp_path):
    import service.portfolio.transactions as tx
    from tests.conftest import FakeTransactions, option_leg

    _set_properties(monkeypatch, tmp_path, "trades.group_ratio_spreads=true\n")

    legs = [  # buy 1 /ES 7700 put, sell 2 x 7600 puts, still open
        option_leg("2026-10-15", "OPENING", 1, 40.0, underlying="ES", strike=7700.0),
        option_leg("2026-10-15", "OPENING", -2, 25.0, underlying="ES", strike=7600.0),
    ]
    monkeypatch.setattr(tx, "get_transaction_provider", lambda: FakeTransactions(option_legs=legs))
    [spread], calls = PositionService(provider=FakePositions({})).get_futures_option_position()
    assert calls == []
    assert spread.ratio == "1:2"
    assert spread.strike_price is None and spread.quantity is None
    assert (spread.long_leg.strike_price, spread.short_leg.strike_price) == (7700.0, 7600.0)
    assert spread.trade_price == pytest.approx(10.0)       # 2 x 25 - 1 x 40, net credit per point
    assert spread.total_value == pytest.approx(500.0)      # x $50


def test_ratio_spread_grouping_can_be_turned_off_in_app_properties(monkeypatch, tmp_path):
    import service.portfolio.transactions as tx
    from tests.conftest import FakeTransactions, option_leg

    legs = [
        option_leg("2026-10-15", "OPENING", 1, 40.0, underlying="ES", strike=7700.0),
        option_leg("2026-10-15", "OPENING", -2, 25.0, underlying="ES", strike=7600.0),
    ]
    monkeypatch.setattr(tx, "get_transaction_provider", lambda: FakeTransactions(option_legs=legs))
    _set_properties(monkeypatch, tmp_path, "trades.group_ratio_spreads=false\n")
    puts, _ = PositionService(provider=FakePositions({})).get_futures_option_position()
    assert sorted(p.strike_price for p in puts) == [7600.0, 7700.0]
    assert all(p.ratio is None for p in puts)
