"""Trade feedback: which of the copilot's recommended trades the user
accepted or turned down, and why — so the next recommendation can take it
into account.

Recorded from the copilot widget's Accept / Reject buttons (POST
/api/copilot/feedback) and by the copilot itself when the user says so in
chat (the record_trade_feedback tool, also in Claude Code via the MCP
server). Stored per user in the users DB (api/users.py), never sent to a
broker. The copilot reads it back through get_trade_feedback_summary:
`summarize` (pure, tested in tests/test_copilot_feedback.py) turns the rows
into counts and repeated patterns, so the model gets numbers rather than
re-deriving them. A repeated pattern is only a *suggested* rule change —
the rules themselves (config/app.properties, the strategy docs) change by
reviewed edits, never from here.
"""

import json
import time
from datetime import datetime, timezone
from typing import Optional

REASONS = {
    "credit_too_small": "Credit too small",
    "strike_too_close": "Strike too close to the money",
    "strike_too_far": "Strike too far from the money",
    "wrong_expiration": "Wrong expiration",
    "assignment_loss": "Too much loss if assigned",
    "not_this_underlying": "Not this underlying right now",
    "other": "Other",
}
VERDICTS = ("accepted", "rejected")
SOURCES = ("app", "assistant")

# The same reason on the same underlying this many times is a pattern worth
# a rule change.
PATTERN_MIN = 3
RECENT_REJECTIONS = 10
MAX_LEGS = 8
MAX_NOTE = 500
MAX_STRATEGY = 60
MAX_CONTEXT_JSON = 4000

# Where a repeated reason would be fixed. None: situational, not a rule.
RULE_HINTS = {
    "credit_too_small": "a minimum credit per trade (no setting yet — add one to config/app.properties)",
    "strike_too_close": "the delta ranges (wheel.*_delta_pct); for ratio calls, wheel.ratio_call_max_below_entry_pct",
    "strike_too_far": "the delta ranges (wheel.*_delta_pct)",
    "wrong_expiration": "the expiration window in the strategy doc (options_wheel.md 4a: 3–6 weeks)",
    "assignment_loss": "wheel.ratio_call_max_below_entry_pct or wheel.loss_budget_pct",
    "not_this_underlying": None,
    "other": None,
}


def _connect():
    # Imported here: `api` loads the whole app (api/__init__.py), which
    # imports the copilot — a module-level import would be circular.
    from api.users import _connect as connect_users_db
    return connect_users_db()


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_at REAL NOT NULL,
            source TEXT NOT NULL,
            verdict TEXT NOT NULL,
            underlying TEXT,
            strategy TEXT,
            legs TEXT NOT NULL,
            reason TEXT,
            note TEXT,
            context TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS trade_feedback_user ON trade_feedback (user_id, created_at)")


def _clean(text: Optional[str], limit: int) -> Optional[str]:
    text = (text or "").strip()
    return text[:limit] or None


def record(user_id: int, *, verdict: str, legs: list[dict], source: str, reason: Optional[str] = None,
           note: Optional[str] = None, strategy: Optional[str] = None, context: Optional[dict] = None) -> int:
    """Save one verdict on a recommended trade; returns its id. A rejection
    needs a reason (one of REASONS). Raises ValueError on bad input."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    if verdict == "rejected" and reason not in REASONS:
        raise ValueError(f"A rejection needs a reason: one of {list(REASONS)}")
    if reason is not None and reason not in REASONS:
        raise ValueError(f"reason must be one of {list(REASONS)}")
    if not legs or len(legs) > MAX_LEGS or not all(isinstance(leg, dict) for leg in legs):
        raise ValueError(f"legs must be 1–{MAX_LEGS} leg objects")
    context_json = json.dumps(context, default=str) if context else None
    if context_json and len(context_json) > MAX_CONTEXT_JSON:
        raise ValueError("context is too large")
    underlying = str(legs[0].get("symbol") or "").strip().upper() or None
    with _connect() as conn:
        _ensure_table(conn)
        cur = conn.execute(
            "INSERT INTO trade_feedback (user_id, created_at, source, verdict, underlying, strategy, legs, reason, note, context) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, time.time(), source, verdict, underlying, _clean(strategy, MAX_STRATEGY),
             json.dumps(legs, default=str), reason, _clean(note, MAX_NOTE), context_json),
        )
        return cur.lastrowid


def recent(user_id: int, days: int = 180) -> list[dict]:
    """The user's feedback from the last `days`, newest first."""
    since = time.time() - days * 86400
    with _connect() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT * FROM trade_feedback WHERE user_id = ? AND created_at >= ? ORDER BY created_at DESC, id DESC",
            (user_id, since),
        ).fetchall()
    return [
        {
            "created_at": r["created_at"],
            "source": r["source"],
            "verdict": r["verdict"],
            "underlying": r["underlying"],
            "strategy": r["strategy"],
            "legs": json.loads(r["legs"]),
            "reason": r["reason"],
            "note": r["note"],
            "context": json.loads(r["context"]) if r["context"] else None,
        }
        for r in rows
    ]


def _leg_text(leg: dict) -> str:
    """"SELL 3 /ES 2026-12-11 7500 C @ 121.5" — compact, for the model."""
    kind = {"CALL": "C", "PUT": "P"}.get(str(leg.get("optionType", "")).upper(), leg.get("optionType", ""))
    text = f"{leg.get('side', '')} {leg.get('quantity', '')} {leg.get('symbol', '')} {leg.get('expirationDate', '')} {leg.get('strike', '')} {kind}"
    if leg.get("premium") is not None:
        text += f" @ {leg['premium']}"
    return " ".join(text.split())


def _date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def summarize(rows: list[dict]) -> dict:
    """Counts per underlying and strategy, rejection reasons, the latest
    rejections in full, and the patterns repeated often enough
    (PATTERN_MIN, same reason on the same underlying) to suggest a rule
    change. `rows` newest first, as `recent` returns them."""
    by_trade: dict[tuple, dict] = {}
    by_reason: dict[str, dict] = {}
    patterns: dict[tuple, int] = {}
    for r in rows:
        key = (r["underlying"], r["strategy"])
        entry = by_trade.setdefault(key, {"underlying": r["underlying"], "strategy": r["strategy"], "accepted": 0, "rejected": 0})
        entry[r["verdict"]] += 1
        if r["verdict"] != "rejected":
            continue
        reason = by_reason.setdefault(r["reason"], {"reason": r["reason"], "label": REASONS.get(r["reason"], r["reason"]),
                                                    "count": 0, "underlyings": []})
        reason["count"] += 1
        if r["underlying"] and r["underlying"] not in reason["underlyings"]:
            reason["underlyings"].append(r["underlying"])
        patterns[(r["reason"], r["underlying"])] = patterns.get((r["reason"], r["underlying"]), 0) + 1

    rejections = [r for r in rows if r["verdict"] == "rejected"]
    return {
        "accepted": sum(1 for r in rows if r["verdict"] == "accepted"),
        "rejected": len(rejections),
        "by_underlying_and_strategy": sorted(by_trade.values(), key=lambda e: -(e["accepted"] + e["rejected"])),
        "rejection_reasons": sorted(by_reason.values(), key=lambda e: -e["count"]),
        "recent_rejections": [
            {
                "date": _date(r["created_at"]),
                "underlying": r["underlying"],
                "strategy": r["strategy"],
                "legs": [_leg_text(leg) for leg in r["legs"]],
                "reason": REASONS.get(r["reason"], r["reason"]),
                "note": r["note"],
                "context": r["context"],
            }
            for r in rejections[:RECENT_REJECTIONS]
        ],
        "suggested_rule_changes": [
            {"reason": REASONS[reason], "underlying": underlying, "times": count, "where": RULE_HINTS[reason]}
            for (reason, underlying), count in sorted(patterns.items(), key=lambda kv: -kv[1])
            if count >= PATTERN_MIN and RULE_HINTS.get(reason)
        ],
    }
