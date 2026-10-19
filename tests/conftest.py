"""Shared fixtures: a stand-in broker for TransactionService, and builders
for the legs a provider returns (see TransactionProvider in
service/portfolio/providers/base.py)."""

import pytest

from service.shared.contracts import get_contract_multiplier


class FakeTransactions:
    """A TransactionProvider serving fixed legs, no network."""

    def __init__(self, option_legs=(), equity_legs=()):
        self.option_legs = list(option_legs)
        self.equity_legs = list(equity_legs)

    def fetch_raw_transactions(self, start_date, end_date):
        return []

    def fetch_option_legs(self, start_date, end_date):
        # Copies: the matcher mutates legs while pairing partial fills.
        return [dict(leg) for leg in self.option_legs]

    def fetch_equity_future_legs(self, start_date, end_date):
        return [dict(leg) for leg in self.equity_legs]

    def normalize_futures_symbol(self, symbol):
        # '/ESZ26:XCME' -> 'ES' (root before the month code + 2-digit year)
        if symbol and symbol.startswith("/"):
            return symbol.split(":")[0][1:-3]
        return symbol


def option_leg(date, effect, amount, price, *, strike=700.0, option_type="PUT",
               underlying="SPY", expiration="2026-10-23", close_event=None):
    """One option leg as a provider returns it. amount is signed: negative =
    sold, positive = bought. A closing leg's `date` is when it closed."""
    return {
        "date": date,
        "close_date": expiration,
        "underlying_symbol": underlying,
        "expirationDate": expiration,
        "strike_price": strike,
        "symbol": f"{underlying} {expiration} {strike} {option_type[0]}",
        "price": price,
        "amount": amount,
        "position_effect": effect,
        "option_type": option_type,
        "type": "TRADE",
        "close_event": close_event,
        "total_amount": price * -amount * get_contract_multiplier(underlying),
        "open_price": price if effect == "OPENING" else 0.0,
        "close_price": price if effect == "CLOSING" else 0.0,
        "open_type": ("BTO" if amount > 0 else "STO") if effect == "OPENING" else None,
    }


def equity_leg(date, symbol, amount, price, *, asset_type="EQUITY", multiplier=1):
    """One equity/futures fill. cost is credit-positive / debit-negative and
    already multiplier-adjusted, as providers return it."""
    return {
        "date": date,
        "symbol": symbol,
        "asset_type": asset_type,
        "amount": amount,
        "price": price,
        "cost": -amount * price * multiplier,
    }


@pytest.fixture
def make_service():
    from service.portfolio import TransactionService

    def make(option_legs=(), equity_legs=()):
        return TransactionService(provider=FakeTransactions(option_legs, equity_legs))

    return make
