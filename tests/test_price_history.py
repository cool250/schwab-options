"""Charts' price history (MarketService.get_price_history): support/
resistance levels, caching, and telling "no data" apart from a failure."""

import pytest

from broker.tastytrade import TastytradeAPIError
from service.market import MarketService
from service.market import history
from service.market.errors import MarketDataError
from service.market.history import swing_levels


class FakeCandles:
    def __init__(self, bars=None, error=None):
        self.bars, self.error, self.calls = bars or [], error, 0

    def get_candles(self, symbol, interval, from_ms, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return self.bars


BARS = [{"time": 1_760_000_000_000 + i * 86_400_000, "open": p, "high": p + 1, "low": p - 1, "close": p}
        for i, p in enumerate([100, 102, 105, 103, 101, 99, 98, 100, 104, 106, 103])]


@pytest.fixture(autouse=True)
def clear_cache():
    history.clear_cache()
    yield
    history.clear_cache()


def test_swing_levels():
    highs = [1, 3, 5, 3, 1, 2, 4, 2, 1]
    lows = [0, 2, 4, 2, 0, 1, 3, 1, 0]
    support, resistance = swing_levels(highs, lows, max_levels=2)
    assert resistance == [5, 4]
    assert support == [0]


def test_swing_levels_fall_back_to_extremes_on_a_straight_trend():
    support, resistance = swing_levels([1, 2, 3, 4, 5], [0, 1, 2, 3, 4])
    assert (support, resistance) == ([0], [5])


def test_history_is_cached_per_symbol_and_range():
    client = FakeCandles(BARS)
    svc = MarketService(chain_provider=object(), client=client)
    first = svc.get_price_history("spy", "1M")
    assert len(first["candles"]) == len(BARS)
    assert svc.get_price_history("SPY", "1M") is first
    assert client.calls == 1


def test_no_bars_means_no_history():
    assert MarketService(chain_provider=object(), client=FakeCandles([])).get_price_history("SPY", "1M") is None


def test_unknown_symbol_means_no_history():
    client = FakeCandles(error=TastytradeAPIError(404, "not found"))
    assert MarketService(chain_provider=object(), client=client).get_price_history("NOPE", "1M") is None


def test_a_broker_failure_is_an_error_not_missing_data():
    client = FakeCandles(error=TimeoutError("DXLink handshake timed out"))
    with pytest.raises(MarketDataError):
        MarketService(chain_provider=object(), client=client).get_price_history("SPY", "1M")


def test_a_missing_futures_contract_means_no_history():
    client = FakeCandles(error=TastytradeAPIError(404, "No live futures contracts found for '/ZZ'"))
    assert MarketService(chain_provider=object(), client=client).get_price_history("/ZZ", "1M") is None
