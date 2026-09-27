import logging
import time
from typing import Optional

from broker.schwab import Client as SchwabClient
from service.option_chain_providers import get_option_chain_provider

logger = logging.getLogger(__name__)

# Schwab's /pricehistory endpoint intermittently comes back with
# {"empty": true, "candles": []} for a perfectly valid symbol/params —
# reproduced locally as streaks of up to 3 consecutive empty responses
# among 8 identical back-to-back calls — so a single empty result is
# treated as transient and retried rather than surfaced as "no history
# for this symbol".
_PRICE_HISTORY_RETRIES = 3
_PRICE_HISTORY_RETRY_DELAY = 0.5

# Schwab's own (periodType, period, frequencyType[, frequency]) vocabulary
# for each Charts-page timeframe button. Chosen so denser ranges don't fetch
# more candles than a chart can usefully show — 1D/5D use intraday bars
# (5-min/30-min), everything from 1M up uses daily, and 5Y/MAX step down to
# weekly/monthly so "20 years" isn't 5,000+ daily candles.
_RANGE_PARAMS = {
    "1D":  {"period_type": "day",   "period": 1,  "frequency_type": "minute", "frequency": 5},
    "5D":  {"period_type": "day",   "period": 5,  "frequency_type": "minute", "frequency": 30},
    "1M":  {"period_type": "month", "period": 1,  "frequency_type": "daily",  "frequency": 1},
    "6M":  {"period_type": "month", "period": 6,  "frequency_type": "daily",  "frequency": 1},
    "YTD": {"period_type": "ytd",   "period": 1,  "frequency_type": "daily",  "frequency": 1},
    "1Y":  {"period_type": "year",  "period": 1,  "frequency_type": "daily",  "frequency": 1},
    "5Y":  {"period_type": "year",  "period": 5,  "frequency_type": "weekly", "frequency": 1},
    "MAX": {"period_type": "year",  "period": 20, "frequency_type": "monthly", "frequency": 1},
}
DEFAULT_PRICE_HISTORY_RANGE = "1M"


def _swing_levels(
    highs: list[float], lows: list[float], window: int = 2, max_levels: int = 2
) -> tuple[list[float], list[float]]:
    """Support/resistance from local swing highs/lows: a day's high is a
    resistance candidate if it's the max high within `window` days on both
    sides, a day's low is a support candidate if it's the min low. Simple
    pivot-point heuristic, not a full TA library — good enough to put a
    couple of meaningful horizontal levels on a 30-day chart rather than
    just the series' own top/bottom edge. Falls back to the overall
    max high / min low when the series has no interior turning points
    (e.g. a strong trend with nothing but a straight run up or down)."""
    n = len(highs)
    swing_highs, swing_lows = [], []
    for i in range(window, n - window):
        high_segment = highs[i - window : i + window + 1]
        low_segment = lows[i - window : i + window + 1]
        if highs[i] == max(high_segment):
            swing_highs.append(highs[i])
        if lows[i] == min(low_segment):
            swing_lows.append(lows[i])

    resistance = sorted(set(swing_highs), reverse=True)[:max_levels] or [max(highs)]
    support = sorted(set(swing_lows))[:max_levels] or [min(lows)]
    return support, resistance


class MarketService:
    def __init__(self):
        self.option_chain_provider = get_option_chain_provider()
        self._schwab_client: Optional[SchwabClient] = None  # lazy: only needed for price history

    def _get_schwab_client(self) -> SchwabClient:
        if self._schwab_client is None:
            self._schwab_client = SchwabClient()
        return self._schwab_client

    def get_price_history(self, symbol: str, range_key: str = DEFAULT_PRICE_HISTORY_RANGE) -> Optional[dict]:
        """
        OHLC candles for `symbol` over one of the Charts page's timeframe
        buttons (see _RANGE_PARAMS — "1D", "5D", "1M", "6M", "YTD", "1Y",
        "5Y", "MAX"), plus support/resistance levels derived from swing
        highs/lows in that series. Backed by Schwab regardless of
        CHAIN_PROVIDER (same as Positions/Transactions) — Tastytrade has no
        REST bar endpoint, only live DXLink ticks, so it can't serve a
        historical chart. Best suited to equities; Schwab's price-history
        endpoint may not resolve a bare futures root like "/NQ" the way it
        resolves a stock ticker.

        Returns None if no history is available (bad symbol/range, broker
        error, or a market that hasn't printed inside the requested window).
        """
        params = _RANGE_PARAMS.get(range_key, _RANGE_PARAMS[DEFAULT_PRICE_HISTORY_RANGE])

        history = None
        for attempt in range(_PRICE_HISTORY_RETRIES):
            try:
                history = self._get_schwab_client().get_price_history(
                    symbol,
                    period_type=params["period_type"],
                    period=params["period"],
                    frequency_type=params["frequency_type"],
                    frequency=params["frequency"],
                )
            except Exception as e:
                logger.error("Failed to fetch price history for %s (%s): %s", symbol, range_key, e)
                return None
            if history.candles:
                break
            if attempt < _PRICE_HISTORY_RETRIES - 1:
                time.sleep(_PRICE_HISTORY_RETRY_DELAY)

        if not history.candles:
            return None

        candles = sorted(history.candles, key=lambda c: c.datetime)

        support, resistance = _swing_levels([c.high for c in candles], [c.low for c in candles])

        return {
            "symbol": symbol,
            "range": range_key,
            "candles": [
                {
                    # Full timestamp (not just the date) — 1D/5D are intraday
                    # bars, and collapsing those down to a bare date would
                    # give every candle in the same trading day an identical
                    # x-axis key. The frontend picks how much of this to
                    # actually display based on the selected range.
                    "date": c.get_datetime().isoformat(),
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                }
                for c in candles
            ],
            "support": support,
            "resistance": resistance,
        }

    def get_expirations(self, symbol: str, days_ahead: int = 60):
        """
        List every expiration date actually listed for `symbol` within the next
        `days_ahead` days — weekly, monthly, and daily where the underlying
        offers them — rather than guessing at weekly Fridays client-side.
        Backed by whichever broker CHAIN_PROVIDER selects (see
        service/option_chain_providers.py).

        Returns:
            list[dict]: [{"date": "YYYY-MM-DD", "dte": int}, ...] sorted by dte.
        """
        return self.option_chain_provider.get_expirations(symbol, days_ahead)

    def get_option_chain(self, symbol: str, dte: int, strike_count: int = 20):
        """
        Fetch a normalized option chain (calls + puts merged by strike) for
        the expiration closest to `dte` days out. Backed by whichever broker
        CHAIN_PROVIDER selects (see service/option_chain_providers.py).

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.
            dte (int): Target days-to-expiration.
            strike_count (int): Number of strikes above/below ATM to fetch.

        Returns:
            dict | None: Normalized chain, or None if unavailable.
        """
        return self.option_chain_provider.get_option_chain(symbol, dte, strike_count)
