"""EventService: economic releases from FRED (matched by name), FOMC
decisions from config, earnings / ex-dividend dates from Tastytrade —
each optional, through stand-ins (no network)."""

from datetime import date

import pytest

import service.market.events as events
from service.market.events import EventService


class FakeMetrics:
    def __init__(self, items=None, fail=False):
        self.items, self.fail, self.asked = items or [], fail, None

    def get_market_metrics(self, symbols):
        self.asked = symbols
        if self.fail:
            raise events.TastytradeAPIError(503, "down")
        return self.items


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr(events, "market_today", lambda: date(2026, 10, 25))
    monkeypatch.setattr(events, "get_config", lambda: {"events.fomc_dates": "2026-10-28, 2026-12-09,bad"})
    events._fred_cache.clear()


def test_releases_matched_by_name_in_window_and_deduplicated():
    calls = []

    def http_get(url, params, timeout):
        calls.append(params)
        return FakeResponse({"release_dates": [
            {"release_name": "Consumer Price Index", "date": "2026-11-10"},
            {"release_name": "Consumer Price Index", "date": "2026-11-10"},
            {"release_name": "Employment Situation", "date": "2026-11-06"},
            {"release_name": "H.8 Assets and Liabilities", "date": "2026-10-30"},
            {"release_name": "Gross Domestic Product", "date": "2026-12-30"},
        ]})

    result = EventService(FakeMetrics(), fred_key="k", http_get=http_get).upcoming([], 30)
    econ = [(e["date"], e["name"], e["major"]) for e in result["events"] if e["kind"] == "ECONOMIC"]
    assert econ == [("2026-11-06", "Jobs report", True), ("2026-11-10", "CPI", True)]
    assert calls[0]["include_release_dates_with_no_data"] == "true"
    # Cached for the day.
    EventService(FakeMetrics(), fred_key="k", http_get=http_get).upcoming([], 30)
    assert len(calls) == 1


def test_fomc_from_config_and_bad_entries_noted():
    result = EventService(FakeMetrics(), fred_key="").upcoming([], 14)
    fomc = [e for e in result["events"] if e["kind"] == "FOMC"]
    assert [(e["date"], e["time"], e["major"]) for e in fomc] == [("2026-10-28", "14:00", True)]
    assert any("FRED_API_KEY" in n for n in result["notes"])
    assert any("bad date" in n for n in result["notes"])


def test_earnings_and_ex_dividend_for_tickers_only():
    metrics = FakeMetrics([
        {"symbol": "GOOG", "earnings": {"expected-report-date": "2026-10-28", "time-of-day": "AMC", "estimated": False},
         "dividend-ex-date": "2026-11-02", "dividend-rate-per-share": "0.22"},
        {"symbol": "QQQ", "earnings": {}, "dividend-ex-date": "2026-09-21"},
        {"symbol": "WDAY", "earnings": {"expected-report-date": "2026-11-24"}, "dividend-ex-date": "1970-01-01"},
    ])
    result = EventService(metrics, fred_key="").upcoming(["GOOG", "QQQ", "WDAY", "/ES"], 14)
    company = [(e["date"], e["name"], e["detail"]) for e in result["events"] if e["kind"] in ("EARNINGS", "EX_DIVIDEND")]
    assert company == [("2026-10-28", "GOOG earnings", "after the close"), ("2026-11-02", "GOOG ex-dividend", "$0.22/share")]
    assert metrics.asked == ["GOOG", "QQQ", "WDAY"], "futures roots have no earnings"


def test_an_unavailable_source_is_a_note_not_an_error():
    def broken(url, params, timeout):
        raise events.requests.ConnectionError("no route")

    result = EventService(FakeMetrics(fail=True), fred_key="k", http_get=broken).upcoming(["GOOG"], 14)
    assert [e["kind"] for e in result["events"]] == ["FOMC"]
    assert any("FRED" in n for n in result["notes"]) and any("Earnings" in n for n in result["notes"])
