"""Trade feedback (copilot/feedback.py): thumbs up / down on recommended
trades, stored per user, and the summary the copilot reads back — counts,
reasons, the latest rejections and repeated patterns."""

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from broker.request_context import set_request_user
from copilot import feedback, tools

LEGS = [
    {"symbol": "/ES", "side": "BUY", "optionType": "CALL", "strike": 7400, "quantity": 1, "premium": 182, "expirationDate": "2026-12-11"},
    {"symbol": "/ES", "side": "SELL", "optionType": "CALL", "strike": 7500, "quantity": 3, "premium": 121.5, "expirationDate": "2026-12-11"},
]


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    from api import users
    users.init_db()
    return users


def test_feedback_is_kept_per_user_newest_first(db):
    feedback.record(1, verdict="accepted", legs=LEGS, source="app", strategy="1x3 call ratio", context={"root_result": 8525})
    feedback.record(1, verdict="rejected", legs=LEGS, source="assistant", reason="assignment_loss", note="  too much on the 7700 lots ")
    feedback.record(2, verdict="rejected", legs=LEGS, source="app", reason="credit_too_small")

    rows = feedback.recent(1)
    assert [r["verdict"] for r in rows] == ["rejected", "accepted"]
    assert rows[0]["underlying"] == "/ES" and rows[0]["note"] == "too much on the 7700 lots"
    assert rows[1]["context"] == {"root_result": 8525} and rows[1]["legs"] == LEGS
    assert [r["reason"] for r in feedback.recent(2)] == ["credit_too_small"]


@pytest.mark.parametrize("kwargs, message", [
    ({"verdict": "maybe"}, "verdict"),
    ({"verdict": "rejected"}, "needs a reason"),
    ({"verdict": "rejected", "reason": "vibes"}, "needs a reason"),
    ({"verdict": "accepted", "legs": []}, "legs"),
    ({"verdict": "accepted", "context": {"x": "y" * 5000}}, "too large"),
])
def test_bad_feedback_is_refused(db, kwargs, message):
    with pytest.raises(ValueError, match=message):
        feedback.record(1, **{"legs": LEGS, "source": "app", **kwargs})


def _row(verdict, reason=None, underlying="/ES", strategy="1x3 call ratio", days_ago=0):
    return {"created_at": time.time() - days_ago * 86400, "source": "app", "verdict": verdict, "underlying": underlying,
            "strategy": strategy, "legs": LEGS, "reason": reason, "note": None, "context": None}


def test_summary_counts_reasons_and_flags_repeated_patterns():
    rows = [
        _row("rejected", "assignment_loss", "/NQ"),
        _row("rejected", "assignment_loss", "/NQ"),
        _row("rejected", "assignment_loss", "/NQ"),
        _row("rejected", "assignment_loss", "/ES"),  # same reason, other root: not the /NQ pattern
        _row("rejected", "not_this_underlying", "/NQ"),
        _row("rejected", "not_this_underlying", "/NQ"),
        _row("rejected", "not_this_underlying", "/NQ"),  # repeated, but situational: no rule to change
        _row("accepted", underlying="/ES", strategy="covered call"),
    ]
    summary = feedback.summarize(rows)

    assert (summary["accepted"], summary["rejected"]) == (1, 7)
    assert summary["rejection_reasons"][0] == {"reason": "assignment_loss", "label": "Too much loss if assigned",
                                               "count": 4, "underlyings": ["/NQ", "/ES"]}
    assert summary["suggested_rule_changes"] == [{
        "reason": "Too much loss if assigned", "underlying": "/NQ", "times": 3,
        "where": feedback.RULE_HINTS["assignment_loss"],
    }]
    latest = summary["recent_rejections"][0]
    assert latest["legs"] == ["BUY 1 /ES 2026-12-11 7400 C @ 182", "SELL 3 /ES 2026-12-11 7500 C @ 121.5"]
    assert {"underlying": "/ES", "strategy": "covered call", "accepted": 1, "rejected": 0} in summary["by_underlying_and_strategy"]


def test_summary_of_nothing():
    assert feedback.summarize([]) == {"accepted": 0, "rejected": 0, "by_underlying_and_strategy": [],
                                      "rejection_reasons": [], "recent_rejections": [], "suggested_rule_changes": []}


def test_the_copilot_tools_record_and_read_as_the_signed_in_user(db):
    token = set_request_user(None)
    assert "error" in json.loads(tools.record_trade_feedback("accepted", LEGS))
    set_request_user(7)
    try:
        assert json.loads(tools.record_trade_feedback("rejected", LEGS, reason="strike_too_close", note="too close")) == \
            {"status": "recorded", "verdict": "rejected"}
        assert "error" in json.loads(tools.record_trade_feedback("rejected", LEGS))  # no reason
        summary = json.loads(tools.get_trade_feedback_summary())
        assert summary["rejected"] == 1 and summary["recent_rejections"][0]["note"] == "too close"
    finally:
        set_request_user(None)
    assert feedback.recent(7)[0]["source"] == "assistant"
    del token


def test_thumbs_from_the_app(db):
    from api import copilot as copilot_api
    from api.auth import require_auth

    user = db.create_user("pat", "password123", is_admin=True)
    app = FastAPI()
    app.include_router(copilot_api.router, prefix="/api/copilot")
    app.dependency_overrides[require_auth] = lambda: user
    client = TestClient(app)

    reasons = client.get("/api/copilot/feedback/reasons").json()
    assert {"code": "credit_too_small", "label": "Credit too small"} in reasons
    ok = client.post("/api/copilot/feedback", json={"verdict": "rejected", "legs": LEGS, "reason": "credit_too_small",
                                                    "strategy": "1x3 call ratio", "context": {"credit": 9125}})
    assert ok.status_code == 200
    assert client.post("/api/copilot/feedback", json={"verdict": "rejected", "legs": LEGS}).status_code == 400
    row = feedback.recent(user.id)[0]
    assert (row["source"], row["strategy"], row["context"]) == ("app", "1x3 call ratio", {"credit": 9125})
