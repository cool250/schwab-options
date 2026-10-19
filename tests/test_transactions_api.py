"""Input validation on the transactions routes (api/portfolio/transactions.py). Only
this router is mounted, with a stand-in service: no auth, no broker."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.portfolio import transactions


class StubService:
    def get_option_transactions(self, *args, **kwargs):
        return []

    def get_equity_transactions(self, *args, **kwargs):
        return []


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(transactions.router, prefix="/api/transactions")
    app.dependency_overrides[transactions.get_service] = StubService
    return TestClient(app)


def test_valid_request(client):
    r = client.get("/api/transactions/options", params={"start_date": "2026-10-01", "end_date": "2026-10-31"})
    assert r.status_code == 200


@pytest.mark.parametrize("params", [
    {"end_date": "2026-10-31"},                                         # missing start
    {"start_date": "10/01/2026", "end_date": "2026-10-31"},             # wrong format
    {"start_date": "2026-10-31", "end_date": "2026-10-01"},             # inverted
    {"start_date": "2026-10-01", "end_date": "2026-10-31", "contract_type": "STRADDLE"},
])
def test_bad_option_queries_are_422(client, params):
    assert client.get("/api/transactions/options", params=params).status_code == 422


def test_bad_asset_type_is_422(client):
    r = client.get("/api/transactions/equity",
                   params={"start_date": "2026-10-01", "end_date": "2026-10-31", "asset_type": "BONDS"})
    assert r.status_code == 422
