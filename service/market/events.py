"""Upcoming market events, for the Home page: scheduled US economic releases
(FRED's release calendar), FOMC rate decisions (events.fomc_dates in
config/app.properties — the Fed publishes them a year ahead but has no API)
and the next earnings report and ex-dividend date of given tickers
(Tastytrade's market metrics). Each source is optional: one that's
unavailable contributes nothing and says why in "notes", never an error.

Market-side only: tickers come in from the page, which knows the holdings.
"""

import logging
import os
import threading
from datetime import date, timedelta
from typing import Optional

import requests

from broker.tastytrade import TastytradeAPIError, TastytradeClient, get_shared_client
from utils.app_config import get_config
from utils.market_time import market_today

logger = logging.getLogger(__name__)

FRED_URL = "https://api.stlouisfed.org/fred/releases/dates"

# FRED release name -> (label, time ET, major). Matched by name rather than
# release id, so nothing here depends on FRED's numbering. Major: the
# releases that move index futures most (CPI, jobs, PCE) — Home sizes new
# shorts that expire after one more cautiously.
RELEASES = {
    "Consumer Price Index": ("CPI", "08:30", True),
    "Employment Situation": ("Jobs report", "08:30", True),
    "Personal Income and Outlays": ("PCE", "08:30", True),
    "Producer Price Index": ("PPI", "08:30", False),
    "Gross Domestic Product": ("GDP", "08:30", False),
}

# FRED's calendar changes rarely: one fetch per day per window serves everyone.
_fred_cache: dict[tuple, list[dict]] = {}
_fred_lock = threading.Lock()


def _event(day: str, name: str, kind: str, time: Optional[str] = None, symbol: Optional[str] = None,
           major: bool = False, detail: Optional[str] = None) -> dict:
    return {"date": day, "time": time, "name": name, "kind": kind, "symbol": symbol, "major": major, "detail": detail}


class EventService:
    def __init__(self, client: Optional[TastytradeClient] = None, fred_key: Optional[str] = None,
                 http_get=requests.get):
        self._client = client
        self._fred_key = fred_key if fred_key is not None else os.environ.get("FRED_API_KEY", "")
        self._http_get = http_get

    def upcoming(self, symbols: list[str], days: int) -> dict:
        """Events from today through `days` ahead, soonest first:
        {"events": [{"date", "time" (ET, "HH:MM", or None), "name", "kind":
        "ECONOMIC" | "FOMC" | "EARNINGS" | "EX_DIVIDEND", "symbol", "major",
        "detail"}], "notes": [str]}."""
        start = market_today()
        end = start + timedelta(days=days)
        notes: list[str] = []
        events = self._economic(start, end, notes) + self._fomc(start, end, notes) + self._company(symbols, start, end, notes)
        events.sort(key=lambda e: (e["date"], e["time"] or "99:99", e["name"]))
        return {"events": events, "notes": notes}

    def _economic(self, start: date, end: date, notes: list[str]) -> list[dict]:
        if not self._fred_key:
            notes.append("Economic releases need a FRED API key (FRED_API_KEY).")
            return []
        key = (start.isoformat(), end.isoformat())
        with _fred_lock:
            cached = _fred_cache.get(key)
        if cached is None:
            try:
                response = self._http_get(FRED_URL, params={
                    "api_key": self._fred_key, "file_type": "json",
                    "realtime_start": start.isoformat(), "realtime_end": end.isoformat(),
                    "include_release_dates_with_no_data": "true", "sort_order": "asc", "limit": 1000,
                }, timeout=10)
                response.raise_for_status()
                rows = response.json().get("release_dates", [])
            except (requests.RequestException, ValueError) as e:
                # Never log the URL: it carries the key.
                logger.error("FRED release calendar unavailable: %s", type(e).__name__)
                notes.append("FRED's release calendar didn't respond.")
                return []
            cached = []
            seen = set()
            for row in rows:
                release = RELEASES.get(row.get("release_name"))
                day = row.get("date")
                if not release or not day or not (start.isoformat() <= day <= end.isoformat()) or (day, release[0]) in seen:
                    continue
                seen.add((day, release[0]))
                label, time, major = release
                cached.append(_event(day, label, "ECONOMIC", time=time, major=major))
            with _fred_lock:
                _fred_cache.clear()  # only today's window is worth keeping
                _fred_cache[key] = cached
        return list(cached)

    def _fomc(self, start: date, end: date, notes: list[str]) -> list[dict]:
        events = []
        for raw in str(get_config()["events.fomc_dates"]).split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                notes.append(f"events.fomc_dates has a bad date: {raw[:20]}")
                continue
            if start <= day <= end:
                events.append(_event(day.isoformat(), "FOMC decision", "FOMC", time="14:00", major=True,
                                     detail="Statement 2:00 PM ET, press conference 2:30"))
        return events

    def _company(self, symbols: list[str], start: date, end: date, notes: list[str]) -> list[dict]:
        tickers = [s for s in dict.fromkeys(symbols) if not s.startswith("/")]
        if not tickers:
            return []
        try:
            client = self._client or get_shared_client()
            items = client.get_market_metrics(tickers)
        except (TastytradeAPIError, ValueError, KeyError) as e:
            logger.error("Market metrics unavailable for events: %s", e)
            notes.append("Earnings and dividend dates are unavailable right now.")
            return []
        events = []
        in_window = lambda d: d is not None and start.isoformat() <= d <= end.isoformat()
        for item in items:
            symbol = item.get("symbol")
            earnings = item.get("earnings") or {}
            report = earnings.get("expected-report-date")
            if in_window(report):
                when = {"BTO": "before the open", "BMO": "before the open", "AMC": "after the close"}.get(
                    (earnings.get("time-of-day") or "").upper())
                events.append(_event(report, f"{symbol} earnings", "EARNINGS", symbol=symbol,
                                     detail=when if not earnings.get("estimated") else f"{when or 'time unknown'}, estimated"))
            ex_date = item.get("dividend-ex-date")
            if in_window(ex_date):
                amount = item.get("dividend-rate-per-share")
                events.append(_event(ex_date, f"{symbol} ex-dividend", "EX_DIVIDEND", symbol=symbol,
                                     detail=f"${float(amount):.2f}/share" if amount not in (None, "") else None))
        return events
