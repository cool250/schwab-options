"""service/market/errors.py: the one place broker exceptions become
SymbolNotFound (404) or MarketDataError (502, fixed message)."""

import pytest

from broker.tastytrade import TastytradeAPIError
from service.market.errors import UNAVAILABLE_MESSAGE, MarketDataError, SymbolNotFound, translate_errors


def raise_inside(exc):
    with translate_errors("SPY", "Test fetch"):
        raise exc


def test_a_404_is_symbol_not_found():
    with pytest.raises(SymbolNotFound) as info:
        raise_inside(TastytradeAPIError(404, "not found"))
    assert info.value.symbol == "SPY"


@pytest.mark.parametrize("exc", [
    TastytradeAPIError(500, "internal: secret detail"),
    TimeoutError("DXLink handshake timed out"),
    KeyError("unexpected payload"),
])
def test_anything_else_is_market_data_error_without_its_text(exc):
    with pytest.raises(MarketDataError) as info:
        raise_inside(exc)
    assert str(info.value) == UNAVAILABLE_MESSAGE
    assert info.value.__cause__ is exc


@pytest.mark.parametrize("exc", [SymbolNotFound("SPY", "option chain"), MarketDataError("custom")])
def test_already_translated_errors_pass_through(exc):
    with pytest.raises(type(exc)) as info:
        raise_inside(exc)
    assert info.value is exc
