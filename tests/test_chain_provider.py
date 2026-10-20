"""The Tastytrade chain provider (service/market/chain_providers.py) and the
client caching it relies on — with a stand-in client, no network."""

import time

import pytest

from broker.tastytrade import TastytradeAPIError, TastytradeClient
from service.market.chain_providers import MAX_SCREENER_CONTRACTS, TastytradeOptionChainProvider
from service.market.errors import MarketDataError, SymbolNotFound


def tt_contract(strike, type_="P", exp="2026-11-20", dte=30):
    return {"strike-price": str(strike), "option-type": type_, "expiration-date": exp, "days-to-expiration": dte,
            "streamer-symbol": f".X{exp}{type_}{strike}", "underlying-symbol": "X"}


LISTED = [tt_contract(k, t, exp, dte) for exp, dte in (("2026-11-20", 30), ("2026-11-27", 37))
          for k in range(80, 131) for t in ("P", "C")]


class FakeClient:
    def __init__(self, snapshot_error=None, listed=LISTED, spot=105.0):
        self.snapshot_error, self.listed, self.spot = snapshot_error, listed, spot
        self.sessions = 0

    def get_options_chain(self, symbol, dte=None, expiration_date=None, min_dte=None, max_dte=None,
                          option_type="all", fetch_live_price=False, **kw):
        if symbol == "NOPE":
            raise TastytradeAPIError(404, "not found")
        items = self.listed
        if expiration_date:
            items = [i for i in items if i["expiration-date"] == expiration_date]
        elif dte is not None:
            closest = min({i["days-to-expiration"] for i in items}, key=lambda d: abs(d - dte))
            items = [i for i in items if i["days-to-expiration"] == closest]
        else:
            items = [i for i in items if (min_dte or 0) <= i["days-to-expiration"] <= (max_dte or 999)]
        return items

    nearest_strikes = staticmethod(TastytradeClient.nearest_strikes)

    def _snapshot(self, contracts):
        if self.snapshot_error:
            raise self.snapshot_error
        syms = [c["streamer-symbol"] for c in contracts]
        return {"spot": self.spot, "quotes": {s: {"bid": 1.0, "ask": 1.2} for s in syms},
                "greeks": {s: {"delta": -0.3, "iv": 0.25} for s in syms}, "volume": {}, "open_interest": {}}

    def get_spot_and_snapshot(self, symbol, select, timeout=5.0):
        self.sessions += 1
        contracts = select(self.spot)
        return {**self._snapshot(contracts), "contracts": contracts}

    def get_chain_snapshot(self, symbol, contracts, timeout=5.0, known_spot=None):
        self.sessions += 1
        return self._snapshot(contracts)


def test_chain_for_an_exact_expiration_in_one_session():
    client = FakeClient()
    chain = TastytradeOptionChainProvider(client).get_option_chain("X", strike_count=5, expiration_date="2026-11-27")
    assert chain["expirationDate"] == "2026-11-27" and chain["dte"] == 37
    assert [r["strikePrice"] for r in chain["chain"]] == [float(k) for k in range(100, 110)]
    assert chain["iv"] == 0.25
    assert client.sessions == 1


def test_known_spot_skips_the_spot_fetch():
    chain = TastytradeOptionChainProvider(FakeClient()).get_option_chain("X", dte=30, strike_count=2, spot=120.0)
    assert chain["spot"] == 120.0
    strikes = [r["strikePrice"] for r in chain["chain"]]
    assert len(strikes) == 4 and {119.0, 120.0, 121.0} <= set(strikes)  # centered on the given spot


def test_a_quote_failure_is_an_error_not_an_unpriced_chain():
    provider = TastytradeOptionChainProvider(FakeClient(snapshot_error=TimeoutError("DXLink")))
    with pytest.raises(MarketDataError):
        provider.get_option_chain("X", dte=30)


def test_unknown_symbol_is_not_found():
    with pytest.raises(SymbolNotFound):
        TastytradeOptionChainProvider(FakeClient()).get_option_chain("NOPE", dte=30)


def test_nothing_listed_is_none():
    assert TastytradeOptionChainProvider(FakeClient(listed=[])).get_screener_contracts("X", 0, 60, ["PUT"], 0, 10) is None


def test_screener_band_and_cap():
    many = [tt_contract(k / 10, "P", f"2026-12-{d:02d}", 40 + d) for d in range(1, 21) for k in range(900, 1100)]
    result = TastytradeOptionChainProvider(FakeClient(listed=many, spot=100.0)).get_screener_contracts(
        "X", 0, 90, ["PUT"], -10, 10)
    assert result["truncated"] is True
    assert len(result["contracts"]) == MAX_SCREENER_CONTRACTS
    assert all(90 <= c["strike"] <= 110 for c in result["contracts"])


# --- client caching -----------------------------------------------------

def make_client(monkeypatch):
    client = TastytradeClient(client_secret="s", refresh_token="r")
    calls = []

    def fake_get(path, params=None):
        calls.append(path)
        if path == "/api-quote-tokens":
            expires = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 86400))
            return {"data": {"token": "t", "dxlink-url": "wss://x", "expires-at": expires}}
        return {"data": {"items": [{"n": len(calls)}]}}

    monkeypatch.setattr(client, "get", fake_get)
    return client, calls


def test_quote_token_is_reused_until_near_expiry(monkeypatch):
    client, calls = make_client(monkeypatch)
    client.get_quote_token()
    client.get_quote_token()
    assert calls.count("/api-quote-tokens") == 1


def test_chain_metadata_is_cached_briefly(monkeypatch):
    client, calls = make_client(monkeypatch)
    assert client.get_option_chain("SPY") == client.get_option_chain("SPY")
    assert calls == ["/option-chains/SPY"]
    client.get_option_chain("QQQ")
    assert len(calls) == 2
    monkeypatch.setattr(TastytradeClient, "METADATA_TTL", 0.0)
    client.get_option_chain("SPY")
    assert len(calls) == 3
