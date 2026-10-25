"""Which broker Portfolio reads: the user's choice from Settings
(service/portfolio/providers, api/portfolio/positions.py's /brokers and
/broker, api/users.set_broker)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from broker.request_context import set_selected_broker
from service.portfolio import providers
from service.portfolio.providers import DEFAULT_BROKER, PortfolioBroker, get_broker


@pytest.fixture
def other_broker():
    """A second registered broker for the length of one test."""
    providers.register(PortfolioBroker("other", "Other", object, object))
    yield "other"
    providers._BROKERS.pop("other", None)


def test_request_reads_the_users_broker(other_broker):
    set_selected_broker(other_broker)
    try:
        assert get_broker().name == "other"
    finally:
        set_selected_broker(None)
    assert get_broker().name == DEFAULT_BROKER


def test_unknown_or_unset_broker_falls_back_to_the_default():
    set_selected_broker("not-registered")
    try:
        assert get_broker().name == DEFAULT_BROKER
    finally:
        set_selected_broker(None)
    assert get_broker(None).name == DEFAULT_BROKER


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    from api import users
    users.init_db()
    return users


def test_choosing_a_broker_clears_the_chosen_account(db, other_broker):
    user = db.create_user("pat", "password123")
    db.set_broker_account(user.id, "12345678")
    db.set_broker(user.id, other_broker)
    saved = db.get_user(user.id)
    assert (saved.broker, saved.broker_account) == ("other", None)


@pytest.fixture
def client(db):
    from api.auth import require_auth
    from api.portfolio import positions
    user = db.create_user("sam", "password123")
    app = FastAPI()
    app.include_router(positions.router, prefix="/api/portfolio/positions")
    app.dependency_overrides[require_auth] = lambda: db.get_user(user.id)
    return TestClient(app), user


def test_brokers_route_marks_the_choice_and_put_saves_it(client, other_broker, db):
    http, user = client
    assert {b["name"]: b["selected"] for b in http.get("/api/portfolio/positions/brokers").json()} == {"schwab": True, "other": False}
    r = http.put("/api/portfolio/positions/broker", json={"name": "other"})
    assert {b["name"]: b["selected"] for b in r.json()} == {"schwab": False, "other": True}
    assert db.get_user(user.id).broker == "other"


def test_put_rejects_a_broker_that_isnt_registered(client):
    http, _ = client
    assert http.put("/api/portfolio/positions/broker", json={"name": "tastytrade"}).status_code == 404
