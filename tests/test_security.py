"""Login throttling (api/login_limits.py), log redaction and the security
headers (api/security.py). The login route is mounted alone with a stand-in
users.authenticate: no database."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from api import auth, login_limits
from api.login_limits import LoginLimiter, MAX_FAILURES_PER_IP, MAX_FAILURES_PER_USERNAME, WINDOW_SECONDS
from api.security import (RedactTokenFilter, api_docs_urls, content_security_policy, inline_script_hashes,
                          install_security_headers, redact_tokens)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_username_is_throttled_after_its_limit_until_the_window_passes():
    clock = Clock()
    limiter = LoginLimiter(clock)
    for _ in range(MAX_FAILURES_PER_USERNAME):
        assert limiter.retry_after("Alice", "1.1.1.1") == 0
        limiter.record_failure("Alice", "1.1.1.1")
    # Case and surrounding spaces don't make it a different username.
    assert limiter.retry_after(" alice ", "2.2.2.2") > 0
    assert limiter.retry_after("bob", "2.2.2.2") == 0
    clock.now += WINDOW_SECONDS
    assert limiter.retry_after("alice", "2.2.2.2") == 0


def test_address_is_throttled_across_usernames():
    limiter = LoginLimiter(Clock())
    for i in range(MAX_FAILURES_PER_IP):
        limiter.record_failure(f"user{i}", "1.1.1.1")
    assert limiter.retry_after("someone-new", "1.1.1.1") > 0
    assert limiter.retry_after("someone-new", "2.2.2.2") == 0


def test_success_clears_the_username_but_not_the_address():
    limiter = LoginLimiter(Clock())
    for i in range(MAX_FAILURES_PER_IP - 1):
        limiter.record_failure("alice" if i < MAX_FAILURES_PER_USERNAME else f"guess{i}", "1.1.1.1")
    limiter.record_success("alice")
    limiter.record_failure("alice", "1.1.1.1")
    assert limiter.retry_after("alice", "9.9.9.9") == 0
    assert limiter.retry_after("alice", "1.1.1.1") > 0


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(login_limits, "limiter", LoginLimiter(Clock()))
    monkeypatch.setattr(auth, "login_limiter", login_limits.limiter)
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    class User:
        id = 7
        username = "alice"

        def public(self):
            return {"id": 7, "username": "alice"}

    monkeypatch.setattr(auth.users, "authenticate", lambda u, p: User() if p == "right" else None)
    monkeypatch.setattr(auth.users, "set_password", lambda user_id, password: None)
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    app.dependency_overrides[auth.require_auth] = User
    return TestClient(app)


def test_login_route_returns_429_after_repeated_failures_without_checking_the_password(client, monkeypatch):
    for _ in range(MAX_FAILURES_PER_USERNAME):
        assert client.post("/api/auth/login", json={"username": "alice", "password": "wrong"}).status_code == 401
    checked = []
    monkeypatch.setattr(auth.users, "authenticate", lambda u, p: checked.append(p))
    res = client.post("/api/auth/login", json={"username": "alice", "password": "right"})
    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) > 0
    assert checked == []


def test_login_uses_flys_client_ip_header(client):
    for i in range(MAX_FAILURES_PER_IP):
        client.post("/api/auth/login", json={"username": f"u{i}", "password": "wrong"},
                    headers={"Fly-Client-IP": "5.5.5.5"})
    blocked = client.post("/api/auth/login", json={"username": "new", "password": "right"},
                          headers={"Fly-Client-IP": "5.5.5.5"})
    allowed = client.post("/api/auth/login", json={"username": "new", "password": "right"},
                          headers={"Fly-Client-IP": "6.6.6.6"})
    assert blocked.status_code == 429
    assert allowed.status_code == 200 and allowed.json()["token"]


def test_websocket_tokens_are_redacted_from_log_lines():
    assert redact_tokens("/api/market/ws/chain?token=abc.def&x=1") == "/api/market/ws/chain?token=<redacted>&x=1"
    record = logging.LogRecord("uvicorn.error", logging.INFO, "", 0, '%s - "WebSocket %s" [accepted]',
                               ("1.2.3.4:5", "/api/market/ws/chain?token=dTE6MTIz.sig"), None)
    RedactTokenFilter().filter(record)
    assert record.getMessage() == '1.2.3.4:5 - "WebSocket /api/market/ws/chain?token=<redacted>" [accepted]'


def test_csp_allows_only_the_inline_scripts_index_html_has(tmp_path):
    index = tmp_path / "index.html"
    index.write_text("<script>var a = 1;</script><script type=\"module\" src=\"/assets/x.js\"></script>")
    hashes = inline_script_hashes(index)
    assert len(hashes) == 1 and hashes[0].startswith("'sha256-")
    csp = content_security_policy(hashes)
    assert f"script-src 'self' {hashes[0]}" in csp
    assert "frame-ancestors 'none'" in csp
    assert inline_script_hashes(tmp_path / "missing.html") == []


def test_change_password_is_throttled_and_shares_the_login_count(client, monkeypatch):
    def change(current):
        return client.post("/api/auth/password", json={"currentPassword": current, "newPassword": "new-password"})

    assert change("right").status_code == 200
    for _ in range(MAX_FAILURES_PER_USERNAME):
        assert change("wrong").status_code == 400
    checked = []
    monkeypatch.setattr(auth.users, "authenticate", lambda u, p: checked.append(p))
    res = change("right")
    assert res.status_code == 429 and int(res.headers["Retry-After"]) > 0
    assert checked == []
    # The same username is now throttled at login too.
    assert client.post("/api/auth/login", json={"username": "alice", "password": "right"}).status_code == 429


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_off_on_fly(monkeypatch, path):
    monkeypatch.setenv("FLY_APP_NAME", "options-wheel")
    assert TestClient(FastAPI(**api_docs_urls())).get(path).status_code == 404
    monkeypatch.delenv("FLY_APP_NAME")
    assert TestClient(FastAPI(**api_docs_urls())).get(path).status_code == 200


def test_security_headers_are_on_api_and_spa_responses(tmp_path):
    (tmp_path / "index.html").write_text("<script>var t = 1;</script><div id=root></div>")
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    install_security_headers(app, tmp_path / "index.html")
    app.mount("/", StaticFiles(directory=str(tmp_path), html=True))
    client = TestClient(app)
    expected = inline_script_hashes(tmp_path / "index.html")[0]
    for path in ("/api/ping", "/"):
        res = client.get(path)
        assert res.status_code == 200
        assert expected in res.headers["Content-Security-Policy"]
        assert res.headers["X-Frame-Options"] == "DENY"
        assert res.headers["X-Content-Type-Options"] == "nosniff"
