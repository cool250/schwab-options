"""Input validation and "nothing found" handling on the Market routes
(api/market/). Only those routers are mounted, with a stand-in service: no
auth, no Tastytrade."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.market import chains, history
from api.market.params import normalize_symbol


class StubService:
    def __init__(self, found=True):
        self.found = found
        self.calls = []

    def get_expirations(self, symbol, days_ahead=60):
        self.calls.append(("expirations", symbol, days_ahead))
        return []

    def get_option_chain(self, symbol, dte=None, expiration_date=None):
        self.calls.append(("chain", symbol, dte, expiration_date))
        if not self.found:
            return None
        return {"symbol": symbol, "spot": 100.0, "dte": dte or 30, "expirationDate": "2026-11-20", "iv": 0.2, "chain": []}

    def get_price_history(self, symbol, range_key):
        self.calls.append(("history", symbol, range_key))
        if not self.found:
            return None
        return {"symbol": symbol, "range": range_key, "candles": [], "support": [], "resistance": []}


def make_client(service):
    app = FastAPI()
    app.include_router(chains.router, prefix="/api/market")
    app.include_router(history.router, prefix="/api/market")
    app.dependency_overrides[chains.get_service] = lambda: service
    app.dependency_overrides[history.get_service] = lambda: service
    return TestClient(app)


@pytest.mark.parametrize("raw, expected", [("spy", "SPY"), (" brk/b ", "BRK/B"), ("/es", "/ES"), ("SPX", "SPX")])
def test_symbols_are_normalized(raw, expected):
    assert normalize_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", "1SPY", "SPY;DROP", "//ES", "ABCDEFGHIJKLM", "S P Y"])
def test_bad_symbols_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_symbol(raw)


def test_route_receives_the_normalized_symbol():
    service = StubService()
    r = make_client(service).get("/api/market/options/expiration-list", params={"symbol": "/es"})
    assert r.status_code == 200
    assert service.calls == [("expirations", "/ES", 60)]


@pytest.mark.parametrize("path", ["/api/market/options/expiration-list", "/api/market/price-history"])
def test_bad_symbol_is_422(path):
    assert make_client(StubService()).get(path, params={"symbol": "SPY;DROP"}).status_code == 422


def test_chain_needs_an_expiration_or_a_dte():
    assert make_client(StubService()).get("/api/market/options/chain", params={"symbol": "SPY"}).status_code == 422


def test_chain_passes_the_expiration_as_an_iso_date():
    service = StubService()
    r = make_client(service).get("/api/market/options/chain", params={"symbol": "SPY", "expiration": "2026-11-20"})
    assert r.status_code == 200
    assert service.calls == [("chain", "SPY", None, "2026-11-20")]


def test_missing_chain_is_404():
    r = make_client(StubService(found=False)).get("/api/market/options/chain", params={"symbol": "SPY", "dte": 30})
    assert r.status_code == 404


def test_unknown_range_is_422():
    r = make_client(StubService()).get("/api/market/price-history", params={"symbol": "SPY", "range": "2W"})
    assert r.status_code == 422


def test_missing_history_is_404():
    r = make_client(StubService(found=False)).get("/api/market/price-history", params={"symbol": "SPY"})
    assert r.status_code == 404
