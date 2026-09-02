import logging
from datetime import datetime, timedelta
from typing import Optional

from broker.schwab import Client as SchwabClient
from service.option_chain_providers import get_option_chain_provider

logger = logging.getLogger(__name__)


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

    def get_price_history(self, symbol: str, days: int = 30) -> Optional[dict]:
        """
        Daily OHLC candles for `symbol` over the last `days` calendar days,
        plus support/resistance levels derived from swing highs/lows in that
        series. Backed by Schwab regardless of BROKER_PROVIDER (same as
        Positions/Transactions) — Tastytrade has no REST daily-bar endpoint,
        only live DXLink ticks, so it can't serve a historical chart. Best
        suited to equities; Schwab's price-history endpoint may not resolve
        a bare futures root like "/NQ" the way it resolves a stock ticker.

        Returns None if no history is available (bad symbol, broker error,
        or a market that hasn't printed inside the requested window).
        """
        try:
            # 2 months of buffer so filtering down to `days` calendar days
            # below still has enough trading days even after weekends/holidays.
            history = self._get_schwab_client().get_price_history(
                symbol, period_type="month", period=2, frequency_type="daily"
            )
        except Exception as e:
            logger.error("Failed to fetch price history for %s: %s", symbol, e)
            return None

        cutoff = datetime.now() - timedelta(days=days)
        candles = sorted(
            (c for c in history.candles if c.get_datetime() >= cutoff),
            key=lambda c: c.datetime,
        )
        if not candles:
            return None

        support, resistance = _swing_levels([c.high for c in candles], [c.low for c in candles])

        return {
            "symbol": symbol,
            "candles": [
                {
                    "date": c.get_datetime().strftime("%Y-%m-%d"),
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
        Backed by whichever broker BROKER_PROVIDER selects (see
        service/option_chain_providers.py).

        Returns:
            list[dict]: [{"date": "YYYY-MM-DD", "dte": int}, ...] sorted by dte.
        """
        return self.option_chain_provider.get_expirations(symbol, days_ahead)

    def get_option_chain(self, symbol: str, dte: int, strike_count: int = 20):
        """
        Fetch a normalized option chain (calls + puts merged by strike) for
        the expiration closest to `dte` days out. Backed by whichever broker
        BROKER_PROVIDER selects (see service/option_chain_providers.py).

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.
            dte (int): Target days-to-expiration.
            strike_count (int): Number of strikes above/below ATM to fetch.

        Returns:
            dict | None: Normalized chain, or None if unavailable.
        """
        return self.option_chain_provider.get_option_chain(symbol, dte, strike_count)
