"""Price history for the Charts page: OHLC candles from Tastytrade's DXLink
Candle feed, plus one support and one resistance level."""

import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

from broker.tastytrade import TastytradeClient
from service.market.errors import SymbolNotFound, translate_errors
from utils.market_time import MARKET_TZ

logger = logging.getLogger(__name__)

# Charts-page timeframe button → DXLink candle request (see
# TastytradeClient.get_candles). Chosen so denser ranges don't fetch more
# bars than a chart can usefully show — 1D/5D use regular-session intraday
# bars (5-min/30-min), 1M–1Y daily, and 5Y/MAX monthly. 5Y is monthly, not
# weekly: DXLink's weekly history only reaches back a few months and its
# daily history ~2 years, while monthly goes back decades.
#   lookback_days  how far back to request (intraday ranges over-fetch to
#                  span weekends/holidays, then keep the last `sessions`)
#   ytd            start at Jan 1 instead of a fixed lookback
RANGE_PARAMS = {
    "1D":  {"interval": "5m",  "lookback_days": 5,   "regular_hours_only": True, "sessions": 1},
    "5D":  {"interval": "30m", "lookback_days": 9,   "regular_hours_only": True, "sessions": 5},
    "1M":  {"interval": "1d",  "lookback_days": 31},
    "6M":  {"interval": "1d",  "lookback_days": 183},
    "YTD": {"interval": "1d",  "ytd": True},
    "1Y":  {"interval": "1d",  "lookback_days": 366},
    "5Y":  {"interval": "1mo", "lookback_days": 365 * 5 + 2},
    "MAX": {"interval": "1mo", "lookback_days": 365 * 20 + 5},
}
DEFAULT_RANGE = "1M"
_INTRADAY_INTERVALS = ("5m", "30m")
# A DXLink candle subscription occasionally delivers nothing on the first
# try; one retry before reporting "no history". Each attempt waits at most
# _TIMEOUT for the first bar — a healthy request answers in well under a
# second, so waiting longer only delays the "no history" page.
_ATTEMPTS = 2
_TIMEOUT = 8.0

# Successful results, per (symbol, range). dxFeed appears to throttle
# *repeat* long-history requests (a monthly-bar request can answer
# instantly once, then return nothing for the same series on the next
# connection), so re-opening a chart shouldn't re-request it. TTLs match how
# fast each bar size changes; the size cap keeps arbitrary symbols from
# growing it without bound (it's shared market data, not account data).
_TTL = {"5m": 60, "30m": 60, "1d": 600, "1mo": 12 * 3600}
_CACHE_SIZE = 200
_cache: "OrderedDict[tuple[str, str], tuple[float, dict]]" = OrderedDict()
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def swing_levels(
    highs: list[float], lows: list[float], window: int = 2, max_levels: int = 2
) -> tuple[list[float], list[float]]:
    """Support/resistance from local swing highs/lows: a bar's high is a
    resistance candidate if it's the max high within `window` bars on both
    sides, a bar's low is a support candidate if it's the min low. A simple
    pivot-point heuristic, not a TA library. Falls back to the overall max
    high / min low when the series has no interior turning points (a
    straight run up or down)."""
    swing_highs, swing_lows = [], []
    for i in range(window, len(highs) - window):
        if highs[i] == max(highs[i - window : i + window + 1]):
            swing_highs.append(highs[i])
        if lows[i] == min(lows[i - window : i + window + 1]):
            swing_lows.append(lows[i])
    resistance = sorted(set(swing_highs), reverse=True)[:max_levels] or [max(highs)]
    support = sorted(set(swing_lows))[:max_levels] or [min(lows)]
    return support, resistance


def get_price_history(client: TastytradeClient, symbol: str, range_key: str = DEFAULT_RANGE) -> Optional[dict]:
    """OHLC candles for `symbol` over one of the Charts page's timeframe
    buttons (RANGE_PARAMS), plus support/resistance from swing highs/lows.
    A futures root ("/ES") resolves to its active-month contract, so long
    ranges show that contract's own history, not a continuous series.

    Candle "date"s: intraday bars carry a full New York timestamp with its
    offset (e.g. "2026-10-09T15:55:00-04:00"), so the browser shows exchange
    times correctly in any timezone; daily/monthly bars are stamped by dxFeed
    at 00:00 UTC of their day, so they're returned as that date at local
    midnight ("2026-10-09T00:00:00").

    Returns None when there's no history (unknown symbol, or nothing printed
    in the window). Raises MarketDataError when Tastytrade fails.
    """
    params = RANGE_PARAMS.get(range_key) or RANGE_PARAMS[DEFAULT_RANGE]
    range_key = range_key if range_key in RANGE_PARAMS else DEFAULT_RANGE
    interval = params["interval"]
    key = (symbol, range_key)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _TTL[interval]:
            _cache.move_to_end(key)
            return hit[1]

    now_ms = int(time.time() * 1000)
    if params.get("ytd"):
        jan1 = MARKET_TZ.localize(datetime(datetime.now(MARKET_TZ).year, 1, 1))
        from_ms = int(jan1.timestamp() * 1000)
    else:
        from_ms = now_ms - params["lookback_days"] * 86_400_000

    bars: list[dict] = []
    try:
        with translate_errors(symbol, "Price history"):
            for _ in range(_ATTEMPTS):
                bars = client.get_candles(
                    symbol, interval, from_ms,
                    regular_hours_only=params.get("regular_hours_only", False),
                    timeout=_TIMEOUT,
                )
                if bars:
                    break
    except SymbolNotFound:
        return None
    if not bars:
        return None

    intraday = interval in _INTRADAY_INTERVALS
    if intraday:
        def session(b: dict):
            return datetime.fromtimestamp(b["time"] / 1000, MARKET_TZ).date()
        keep = sorted({session(b) for b in bars})[-params["sessions"]:]
        bars = [b for b in bars if session(b) in keep]

    def bar_date(b: dict) -> str:
        if intraday:
            return datetime.fromtimestamp(b["time"] / 1000, MARKET_TZ).isoformat()
        return datetime.fromtimestamp(b["time"] / 1000, timezone.utc).strftime("%Y-%m-%dT00:00:00")

    support, resistance = swing_levels([b["high"] for b in bars], [b["low"] for b in bars], max_levels=1)
    result = {
        "symbol": symbol,
        "range": range_key,
        # Full timestamps, not bare dates — 1D/5D bars share a trading day,
        # and the frontend picks how much of it to show per range.
        "candles": [
            {"date": bar_date(b), "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]}
            for b in bars
        ],
        "support": support,
        "resistance": resistance,
    }
    with _cache_lock:
        _cache[key] = (time.time(), result)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return result
