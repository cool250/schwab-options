"""Market quotes (service/market/quotes.py): matching broker-neutral contract
descriptions to Tastytrade chain entries, through a stand-in client."""

from datetime import date

from service.market import QuoteService


class FakeTastytrade:
    def __init__(self):
        self.calls = []

    def get_option_chain(self, ticker):
        self.calls.append(("equity", ticker))
        return [
            {"strike-price": "700.0", "option-type": "P", "expiration-date": "2026-10-23", "streamer-symbol": ".QQQ261023P700"},
            {"strike-price": "700.0", "option-type": "P", "expiration-date": "2026-10-30", "streamer-symbol": ".QQQ261030P700"},
            {"strike-price": "710.0", "option-type": "C", "expiration-date": "2026-10-23", "streamer-symbol": ".QQQ261023C710"},
        ]

    def get_future_option_chain(self, symbol, expiration_date):
        self.calls.append(("futures", symbol, expiration_date))
        return [{"strike-price": "7650", "option-type": "P", "streamer-symbol": "./E3DV26P7650"}]

    def get_chain_quotes(self, contracts, with_theta=False):
        quotes = {
            ".QQQ261023P700": {"bid": 2.0, "ask": 2.2, "theta": -0.05, "delta": -0.3},
            ".QQQ261030P700": {"bid": 4.0, "ask": None, "theta": None},
            "./E3DV26P7650": {"bid": 18.5, "ask": 19.0, "theta": -1.25},
        }
        return {
            c["streamer-symbol"]: {k: v for k, v in quotes[c["streamer-symbol"]].items() if with_theta or k not in ("theta", "delta")}
            for c in contracts if c["streamer-symbol"] in quotes
        }

    def get_live_underlying_price(self, symbol):
        if symbol == "/ES":
            return 7712.25
        raise TimeoutError("no quote")


def contract(key, underlying, expiration, strike, type_="PUT"):
    return {"key": key, "underlying": underlying, "expiration": expiration, "strike": strike, "type": type_}


def test_equity_matches_on_expiration_too():
    svc = QuoteService(FakeTastytrade())
    result = svc.quote_options([
        contract("a", "QQQ", date(2026, 10, 23), 700),
        contract("b", "qqq", "2026-10-30", 700),
    ])
    assert result["a"] == {"bid": 2.0, "ask": 2.2, "mid": 2.1, "theta": -0.05, "delta": -0.3}
    assert result["b"] == {"bid": 4.0, "ask": None, "mid": None, "theta": None, "delta": None}


def test_futures_root_accepted_with_or_without_slash():
    client = FakeTastytrade()
    result = QuoteService(client).quote_options([
        contract("x", "/ES", "2026-10-20", 7650),
        contract("y", "ES", "2026-10-20", 7650),
    ])
    assert result["x"] == result["y"] == {"bid": 18.5, "ask": 19.0, "mid": 18.75, "theta": -1.25, "delta": None}
    # one chain fetch per (root, expiration)
    assert client.calls == [("futures", "/ES", "2026-10-20")]


def test_unpriceable_contracts_are_absent():
    result = QuoteService(FakeTastytrade()).quote_options([
        contract("no-strike", "QQQ", "2026-10-23", 999),
        contract("no-quote", "QQQ", "2026-10-23", 710, "CALL"),
    ])
    assert result == {}


def test_futures_roots():
    assert QuoteService(FakeTastytrade()).quote_futures(["ES", "NQ"]) == {"ES": 7712.25}


def test_nothing_requested_never_builds_a_client():
    svc = QuoteService()  # no credentials needed for an empty request
    assert svc.quote_options([]) == {} and svc.quote_futures([]) == {}
