"""WatchlistService: change on the day from the previous close, IV from
market metrics, and a row for every symbol even when unpriced."""

from service.market.watchlist import WatchlistService


class FakeClient:
    def get_price_snapshots(self, tickers):
        return {
            "GOOG": {"price": 330.0, "prev_close": 320.0, "day_high": 332.0, "day_low": 318.0},
            "/ES": {"price": 7672.5, "prev_close": 7700.0},
        }

    def get_market_metrics(self, symbols):
        self.asked = symbols
        return [{"symbol": "GOOG", "implied-volatility-index": "0.3858", "implied-volatility-index-rank": "0.6169"}]


def test_rows_in_order_with_change_and_iv():
    client = FakeClient()
    rows = WatchlistService(client).rows(["GOOG", "/ES", "XYZ"])
    assert [r["symbol"] for r in rows] == ["GOOG", "/ES", "XYZ"]
    goog, es, xyz = rows
    assert goog["change"] == 10.0 and abs(goog["change_pct"] - 3.125) < 1e-9
    assert abs(goog["iv"] - 38.58) < 1e-9 and abs(goog["iv_rank"] - 61.69) < 1e-9
    assert es["change"] == -27.5 and es["iv"] is None
    assert xyz["price"] is None and xyz["change"] is None
    assert client.asked == ["GOOG", "XYZ"], "futures roots have no market metrics"
