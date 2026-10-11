import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from broker.schwab import Client as SchwabClient
from broker.schwab.exceptions import BrokerAuthError
from service.option_chain_providers import get_option_chain_provider, otm_pct
from service.screener_strategies import MULTI_LEG_STRATEGIES, STRATEGY_BUILDERS, STRATEGY_OPTION_TYPES

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

# Tickers screened concurrently — each one is a chain fetch plus a DXLink
# snapshot (Tastytrade) or one large chain request (Schwab), mostly spent
# waiting on the network, so a small pool cuts a 10-ticker screen from ~10
# sequential round-trips to ~3 without hammering either broker.
_SCREENER_WORKERS = 4


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

    def screen_options(
        self,
        symbols: list[str],
        min_dte: int,
        max_dte: int,
        min_otm_pct: float,
        max_otm_pct: float,
        strategy: str,
        min_abs_delta: Optional[float] = None,
        max_abs_delta: Optional[float] = None,
        limit: int = 200,
    ) -> dict:
        """
        Rank every put/call across `symbols` that falls inside the DTE and
        moneyness window by how much it returns to *sell* it, best first.
        Backs the Options Screener page.

        `strategy` is one of service.screener_strategies.STRATEGIES: "PUT" /
        "CALL" rank single contracts (fields below); "RATIO_PUT" /
        "JADE_LIZARD" rank multi-leg combinations built within each
        expiration — see screener_strategies.py for their definitions and
        row shape. For those, every leg must sit inside the moneyness band
        and the delta filter applies to the legs being sold.

        `min_abs_delta`/`max_abs_delta` filter on |delta| so one range covers
        both sides (0.15-0.30 keeps a -0.20 put and a 0.20 call). Delta only
        arrives with the quote snapshot, so this narrows the moneyness-band
        fetch rather than replacing it.

        Either delta bound is optional — None leaves that side open. With
        no delta bound at all the filter is off; otherwise a
        contract whose delta didn't come back is excluded, since there's no
        way to know it qualifies.

        Returns per contract (besides the raw quote/greeks fields):
          premium            the bid — what a sell order can actually fill at
                             right now, rather than an optimistic mid.
          capital            cash-secured put: strike. Covered call: spot
                             (the cost of the 100 shares). Per share, like
                             premium, so the ratio is multiplier-agnostic.
          roi                (premium - intrinsic) / capital — the return if
                             the underlying is unchanged at expiration. For
                             OTM strikes this is just premium / capital; for
                             ITM strikes the intrinsic part is subtracted,
                             since it's handed straight back on assignment/
                             call-away — otherwise deep-ITM contracts would
                             top a "max ROI" sort with a return they can't
                             actually deliver.
          annualizedRoi      roi * 365 / dte, so a 7-DTE and a 45-DTE
                             contract can be ranked against each other. This
                             is the sort key.
          breakeven          put: strike - premium; call: spot - premium.

        A ticker that fails to load (bad symbol, no listed options, broker
        hiccup) is reported in "errors" rather than failing the whole screen
        — except a dead Schwab session, which no other ticker would survive
        either, so BrokerAuthError still propagates (-> 503).
        """
        option_types = STRATEGY_OPTION_TYPES[strategy]

        def fetch(symbol: str):
            try:
                return symbol, self.option_chain_provider.get_screener_contracts(
                    symbol, min_dte, max_dte, option_types, min_otm_pct, max_otm_pct
                ), None
            except BrokerAuthError:
                raise
            except Exception as e:
                logger.error("Screener failed for %s: %s", symbol, e)
                if getattr(e, "status_code", None) == 404:
                    return symbol, None, "Symbol not found, or it has no listed options"
                return symbol, None, str(e) or e.__class__.__name__

        with ThreadPoolExecutor(max_workers=min(_SCREENER_WORKERS, len(symbols) or 1)) as pool:
            results = list(pool.map(fetch, symbols))

        delta_filter_on = min_abs_delta is not None or max_abs_delta is not None

        def delta_ok(c: dict) -> bool:
            if not delta_filter_on:
                return True
            return not (
                c["delta"] is None
                or (min_abs_delta is not None and abs(c["delta"]) < min_abs_delta)
                or (max_abs_delta is not None and abs(c["delta"]) > max_abs_delta)
            )

        rows, errors, truncated = [], [], []
        for symbol, result, error in results:
            if error is not None:
                errors.append({"symbol": symbol, "message": error})
                continue
            if not result or not result["contracts"]:
                errors.append({"symbol": symbol, "message": "No contracts in the selected DTE / moneyness range"})
                continue
            rows_before = len(rows)
            if result["truncated"]:
                truncated.append(symbol)

            spot = result["spot"]
            if strategy in MULTI_LEG_STRATEGIES:
                by_expiration: dict[str, list[dict]] = {}
                for c in result["contracts"]:
                    if c["dte"] is not None:
                        by_expiration.setdefault(c["expirationDate"], []).append(c)
                for contracts in by_expiration.values():
                    rows.extend(STRATEGY_BUILDERS[strategy](symbol, spot, contracts, delta_ok))
                if len(rows) == rows_before:
                    errors.append({"symbol": symbol, "message": "No qualifying combinations in the selected range"
                                   + (" and delta range" if delta_filter_on else "")})
                continue

            for c in result["contracts"]:
                bid, dte = c["bid"], c["dte"]
                if not bid or bid <= 0 or dte is None:
                    continue
                if not delta_ok(c):
                    continue
                strike = c["strike"]
                if c["type"] == "PUT":
                    capital, intrinsic, breakeven = strike, max(strike - spot, 0), strike - bid
                else:
                    capital, intrinsic, breakeven = spot, max(spot - strike, 0), spot - bid
                roi = (bid - intrinsic) / capital
                ask = c["ask"]
                rows.append({
                    **c,
                    "strategy": c["type"],
                    "underlying": symbol,
                    "spot": spot,
                    "mid": (bid + ask) / 2 if ask else None,
                    "otmPct": otm_pct(strike, spot, c["type"]),
                    "premium": bid,
                    "capital": capital,
                    "roi": roi * 100,
                    # max(dte, 1): a 0-DTE contract still ties up capital for
                    # the rest of the session — annualize it as one day, not
                    # divide by zero.
                    "annualizedRoi": roi * 365 / max(dte, 1) * 100,
                    "breakeven": breakeven,
                })
            if len(rows) == rows_before:
                errors.append({"symbol": symbol, "message": "No contracts with a live bid matched the delta range"
                               if delta_filter_on else "No contracts with a live bid in the selected range"})

        rows.sort(key=lambda r: r["annualizedRoi"], reverse=True)
        return {
            "results": rows[:limit],
            "totalMatches": len(rows),
            "errors": errors,
            "truncated": truncated,
        }
