"""TastytradeClient.get_future_option_chain builds its flat contract list
from the small '/nested' endpoint (the flat one is ~150 MB parsed for /ES)."""

from broker.tastytrade.client import TastytradeClient


class NestedOnly(TastytradeClient):
    def __init__(self):
        super().__init__(client_id="x", client_secret="y", refresh_token="z")
        self.paths = []

    def get(self, path, params=None):
        self.paths.append(path)
        assert path == "/futures-option-chains/ES/nested"
        return {"data": {"option-chains": [{"expirations": [
            {"expiration-date": "2026-10-30", "days-to-expiration": 5, "underlying-symbol": "/ESZ6",
             "strikes": [{"strike-price": "7000.0", "call": "./ESZ6 EW4V6 261030C7000", "call-streamer-symbol": "./EW4V26C7000:XCME",
                          "put": "./ESZ6 EW4V6 261030P7000", "put-streamer-symbol": "./EW4V26P7000:XCME"}]},
            {"expiration-date": "2026-11-20", "days-to-expiration": 26, "underlying-symbol": "/ESZ6",
             "strikes": [{"strike-price": "6900.0", "put": "./ESZ6 E3BX6 261120P6900", "put-streamer-symbol": "./E3BX26P6900:XCME"}]},
        ]}]}}


def test_flat_chain_built_from_nested_and_cached():
    client = NestedOnly()
    items = client.get_future_option_chain("/ES")
    assert items[0] == {
        "symbol": "./ESZ6 EW4V6 261030C7000", "streamer-symbol": "./EW4V26C7000:XCME", "strike-price": "7000.0",
        "option-type": "C", "expiration-date": "2026-10-30", "days-to-expiration": 5, "underlying-symbol": "/ESZ6",
    }
    assert [i["option-type"] for i in items] == ["C", "P", "P"]
    # Filters still apply, and the nested chain is fetched once.
    assert [i["strike-price"] for i in client.get_future_option_chain("ES", option_type="P", max_dte=10)] == ["7000.0"]
    assert [i["expiration-date"] for i in client.get_future_option_chain("/ES", expiration_date="2026-11-20")] == ["2026-11-20"]
    assert client.paths == ["/futures-option-chains/ES/nested"]
