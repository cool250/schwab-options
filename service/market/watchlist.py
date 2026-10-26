"""Home's watchlist: each ticker's last price, change on the day, day range
and implied volatility — Tastytrade's DXLink feed (one session for all)
plus its market metrics for IV and IV rank. The page sends the tickers (its
positions'); nothing here knows about holdings.
"""

import logging
from typing import Optional

from broker.tastytrade import TastytradeAPIError, TastytradeClient, get_shared_client

logger = logging.getLogger(__name__)


def _pct(value) -> Optional[float]:
    """A metrics fraction ('0.6168') as a percent (61.68), None if absent."""
    try:
        return float(value) * 100 if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class WatchlistService:
    def __init__(self, client: Optional[TastytradeClient] = None):
        self._client = client

    def _get_client(self) -> Optional[TastytradeClient]:
        if self._client is None:
            try:
                self._client = get_shared_client()
            except ValueError as e:
                logger.error("Tastytrade credentials unavailable for the watchlist: %s", e)
        return self._client

    def rows(self, symbols: list[str]) -> list[dict]:
        """One row per symbol, in the order given:
        {"symbol", "price", "change", "change_pct", "prev_close", "day_high",
         "day_low", "iv", "iv_rank"} — iv and iv_rank in percent, for
        equities and ETFs only. Anything unknown is None; a symbol with no
        price at all still gets a row, so the list doesn't reshuffle."""
        client = self._get_client()
        if client is None or not symbols:
            return [{"symbol": s} for s in symbols]
        try:
            snaps = client.get_price_snapshots(symbols)
        except (TastytradeAPIError, ValueError, TimeoutError) as e:
            logger.error("Watchlist prices unavailable: %s", e)
            snaps = {}
        metrics = {}
        equities = [s for s in symbols if not s.startswith("/")]
        if equities:
            try:
                metrics = {m.get("symbol"): m for m in client.get_market_metrics(equities)}
            except (TastytradeAPIError, ValueError, KeyError) as e:
                logger.error("Watchlist IV unavailable: %s", e)
        rows = []
        for symbol in symbols:
            snap = snaps.get(symbol, {})
            price, prev = snap.get("price"), snap.get("prev_close")
            change = price - prev if price is not None and prev else None
            m = metrics.get(symbol, {})
            rows.append({
                "symbol": symbol,
                "price": price,
                "change": change,
                "change_pct": change / prev * 100 if change is not None else None,
                "prev_close": prev,
                "day_high": snap.get("day_high"),
                "day_low": snap.get("day_low"),
                "iv": _pct(m.get("implied-volatility-index")),
                "iv_rank": _pct(m.get("implied-volatility-index-rank")),
            })
        return rows
