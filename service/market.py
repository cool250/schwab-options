import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

import pytz

from broker.tastytrade import TastytradeAPIError, TastytradeClient
from service.option_chain_providers import get_option_chain_provider, otm_pct
from service import strategy_builder
from service.screener_strategies import (
    LONG_STRATEGIES,
    MULTI_LEG_STRATEGIES,
    STRATEGY_BUILDERS,
    STRATEGY_OPTION_TYPES,
)

logger = logging.getLogger(__name__)

# Charts-page timeframe button → Tastytrade DXLink candle request (see
# TastytradeClient.get_candles). Chosen so denser ranges don't fetch more
# bars than a chart can usefully show — 1D/5D use regular-session intraday
# bars (5-min/30-min), 1M–1Y daily, and 5Y/MAX monthly. 5Y is monthly, not
# weekly: DXLink's weekly history only reaches back a few months and its
# daily history ~2 years, while monthly goes back decades.
#   lookback_days  how far back to request (intraday ranges over-fetch to
#                  span weekends/holidays, then keep the last `sessions`)
#   ytd            start at Jan 1 instead of a fixed lookback
_RANGE_PARAMS = {
    "1D":  {"interval": "5m",  "lookback_days": 5,   "regular_hours_only": True, "sessions": 1},
    "5D":  {"interval": "30m", "lookback_days": 9,   "regular_hours_only": True, "sessions": 5},
    "1M":  {"interval": "1d",  "lookback_days": 31},
    "6M":  {"interval": "1d",  "lookback_days": 183},
    "YTD": {"interval": "1d",  "ytd": True},
    "1Y":  {"interval": "1d",  "lookback_days": 366},
    "5Y":  {"interval": "1mo", "lookback_days": 365 * 5 + 2},
    "MAX": {"interval": "1mo", "lookback_days": 365 * 20 + 5},
}
_INTRADAY_INTERVALS = ("5m", "30m")
_ET = pytz.timezone("US/Eastern")
# A DXLink candle subscription occasionally delivers nothing on the first
# try; one retry before reporting "no history". Each attempt waits at most
# _PRICE_HISTORY_TIMEOUT for the first bar — a healthy request answers in
# well under a second, so waiting longer only delays the "no history" page.
_PRICE_HISTORY_ATTEMPTS = 2
_PRICE_HISTORY_TIMEOUT = 8.0

# In-memory cache of successful results, per (symbol, range). dxFeed appears
# to throttle *repeat* long-history requests (a monthly-bar request can
# answer instantly once, then return nothing for the same series on the
# next connection), so re-opening a chart shouldn't re-request it. TTLs
# match how fast each bar size actually changes.
_PRICE_HISTORY_TTL = {"5m": 60, "30m": 60, "1d": 600, "1mo": 12 * 3600}
_price_history_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_price_history_cache_lock = threading.Lock()
DEFAULT_PRICE_HISTORY_RANGE = "1M"

# Tickers screened concurrently — each one is a chain fetch plus a DXLink
# snapshot, mostly spent waiting on the network, so a small pool cuts a
# 10-ticker screen from ~10 sequential round-trips to ~3 without hammering
# Tastytrade.
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
        self._tasty_client: Optional[TastytradeClient] = None  # lazy: only needed for price history

    def _get_tasty_client(self) -> TastytradeClient:
        if self._tasty_client is None:
            self._tasty_client = TastytradeClient.from_config()
        return self._tasty_client

    def get_price_history(self, symbol: str, range_key: str = DEFAULT_PRICE_HISTORY_RANGE) -> Optional[dict]:
        """
        OHLC candles for `symbol` over one of the Charts page's timeframe
        buttons (see _RANGE_PARAMS — "1D", "5D", "1M", "6M", "YTD", "1Y",
        "5Y", "MAX"), plus support/resistance levels derived from swing
        highs/lows in that series.

        Backed by Tastytrade's DXLink Candle feed — no Schwab login needed.
        A futures root ("/ES")
        resolves to its active-month contract, so long ranges show that
        contract's own history rather than a continuous back-adjusted series.

        Candle "date"s: intraday bars carry a full US/Eastern timestamp with
        its offset (e.g. "2026-10-09T15:55:00-04:00"), so the browser shows
        exchange times correctly in any timezone; daily/monthly bars are
        stamped by dxFeed at 00:00 UTC of their day, so they're returned as
        that UTC date at local midnight ("2026-10-09T00:00:00").

        Returns None if no history is available (unknown symbol, or nothing
        printed in the window). Raises TastytradeAPIError for any other
        Tastytrade failure (→ app.py's 502 handler).
        """
        if range_key not in _RANGE_PARAMS:
            range_key = DEFAULT_PRICE_HISTORY_RANGE
        params = _RANGE_PARAMS[range_key]
        interval = params["interval"]
        cache_key = (symbol.strip().upper(), range_key)
        with _price_history_cache_lock:
            hit = _price_history_cache.get(cache_key)
        if hit and time.time() - hit[0] < _PRICE_HISTORY_TTL[interval]:
            return hit[1]

        now_ms = int(time.time() * 1000)
        if params.get("ytd"):
            jan1 = _ET.localize(datetime(datetime.now(_ET).year, 1, 1))
            from_ms = int(jan1.timestamp() * 1000)
        else:
            from_ms = now_ms - params["lookback_days"] * 86_400_000

        bars: list[dict] = []
        for _ in range(_PRICE_HISTORY_ATTEMPTS):
            try:
                bars = self._get_tasty_client().get_candles(
                    symbol, interval, from_ms,
                    regular_hours_only=params.get("regular_hours_only", False),
                    timeout=_PRICE_HISTORY_TIMEOUT,
                )
            except TastytradeAPIError as e:
                if e.status_code == 404:  # unknown symbol: "no history", not a system error
                    return None
                raise
            except Exception as e:  # e.g. no live futures contract for a root, DXLink handshake timeout
                logger.error("Failed to fetch price history for %s (%s): %s", symbol, range_key, e)
                return None
            if bars:
                break
        if not bars:
            return None

        intraday = interval in _INTRADAY_INTERVALS
        if intraday:
            def session(b: dict):
                return datetime.fromtimestamp(b["time"] / 1000, _ET).date()
            keep = sorted({session(b) for b in bars})[-params["sessions"]:]
            bars = [b for b in bars if session(b) in keep]

        def bar_date(b: dict) -> str:
            if intraday:
                return datetime.fromtimestamp(b["time"] / 1000, _ET).isoformat()
            return datetime.fromtimestamp(b["time"] / 1000, timezone.utc).strftime("%Y-%m-%dT00:00:00")

        # One support and one resistance line on the chart.
        support, resistance = _swing_levels([b["high"] for b in bars], [b["low"] for b in bars], max_levels=1)

        result = {
            "symbol": symbol,
            "range": range_key,
            "candles": [
                {
                    # Full timestamp (not just the date) — 1D/5D are intraday
                    # bars, and collapsing those down to a bare date would
                    # give every candle in the same trading day an identical
                    # x-axis key. The frontend picks how much of this to
                    # actually display based on the selected range.
                    "date": bar_date(b),
                    "open": b["open"],
                    "high": b["high"],
                    "low": b["low"],
                    "close": b["close"],
                }
                for b in bars
            ],
            "support": support,
            "resistance": resistance,
        }
        with _price_history_cache_lock:
            _price_history_cache[cache_key] = (time.time(), result)
        return result

    def get_expirations(self, symbol: str, days_ahead: int = 60):
        """
        List every expiration date actually listed for `symbol` within the next
        `days_ahead` days — weekly, monthly, and daily where the underlying
        offers them — rather than guessing at weekly Fridays client-side.
        Backed by Tastytrade (see service/option_chain_providers.py).

        Returns:
            list[dict]: [{"date": "YYYY-MM-DD", "dte": int}, ...] sorted by dte.
        """
        return self.option_chain_provider.get_expirations(symbol, days_ahead)

    def get_option_chain(self, symbol: str, dte: int, strike_count: int = 20):
        """
        Fetch a normalized option chain (calls + puts merged by strike) for
        the expiration closest to `dte` days out. Backed by Tastytrade (see
        service/option_chain_providers.py).

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.
            dte (int): Target days-to-expiration.
            strike_count (int): Number of strikes above/below ATM to fetch.

        Returns:
            dict | None: Normalized chain, or None if unavailable.
        """
        return self.option_chain_provider.get_option_chain(symbol, dte, strike_count)

    def get_strategy_templates(self) -> list[dict]:
        """Strategy Builder templates (service/strategy_builder.py) — the one
        definition the Analyze page's builder form is generated from."""
        return strategy_builder.list_templates()

    def build_strategy(
        self,
        symbol: str,
        dte: int,
        strategy: str,
        params: dict,
        target: Optional[float] = None,
        expiration_date: Optional[str] = None,
        max_dte: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Place `strategy`'s legs on the live chain for the expiration `dte`
        days out, priced at mid — see strategy_builder.build for the solver,
        `params` and `target`. Backs the Analyze page's Strategy Builder.

        `expiration_date` is what the caller selected; the chain provider
        resolves `dte` to the closest listed expiration, and a mismatch is
        reported in "reasons" rather than silently building on another date.

        With `max_dte` > `dte`, builds on every listed expiration in
        [dte, max_dte] instead (at most strategy_builder.MAX_RANGE_EXPIRATIONS)
        and ranks them together — see _build_strategy_range. Every candidate
        carries its own expirationDate/dte; the top-level ones are the best's.

        Returns None if the symbol has no chain. Raises
        strategy_builder.StrategyParamError (-> 422) for bad parameters.
        """
        if max_dte is not None and max_dte > dte:
            return self._build_strategy_range(symbol, dte, max_dte, strategy, params, target)
        try:
            chain = self.option_chain_provider.get_option_chain(symbol, dte, strategy_builder.STRIKE_COUNT)
        except TastytradeAPIError as e:
            if e.status_code == 404:  # unknown symbol: "no chain", not a system error
                return None
            raise
        if chain is None:
            return None
        result = strategy_builder.build(strategy, params, chain, target)
        if expiration_date and chain.get("expirationDate") and chain["expirationDate"] != expiration_date:
            result["reasons"].insert(0, f'Built on {chain["expirationDate"]} — the closest listed expiration to {expiration_date}')
        return {
            "symbol": symbol,
            "strategy": strategy,
            "spot": chain["spot"],
            "iv": chain.get("iv"),
            "dte": chain.get("dte"),
            "expirationDate": chain.get("expirationDate"),
            "expirationsSearched": 1,
            **result,
        }

    def _build_strategy_range(
        self, symbol: str, min_dte: int, max_dte: int, strategy: str, params: dict, target: Optional[float]
    ) -> Optional[dict]:
        # Bad parameters fail fast, before any chain is fetched.
        strategy_builder.resolve_params(strategy, params, target)
        try:
            listed = self.get_expirations(symbol, max_dte)
        except TastytradeAPIError as e:
            if e.status_code == 404:
                return None
            raise
        expirations = [e for e in listed if min_dte <= e["dte"] <= max_dte]
        if not expirations:
            return None
        if len(expirations) > strategy_builder.MAX_RANGE_EXPIRATIONS:
            raise strategy_builder.StrategyParamError(
                f"{len(expirations)} expirations fall in that range — narrow it to at most "
                f"{strategy_builder.MAX_RANGE_EXPIRATIONS}"
            )

        def fetch(expiration: dict):
            try:
                return expiration, self.option_chain_provider.get_option_chain(
                    symbol, expiration["dte"], strategy_builder.STRIKE_COUNT
                ), None
            except Exception as e:  # one bad expiration shouldn't sink the rest
                logger.error("Strategy build: chain for %s %s failed: %s", symbol, expiration["date"], e)
                return expiration, None, str(e) or e.__class__.__name__

        with ThreadPoolExecutor(max_workers=min(_SCREENER_WORKERS, len(expirations))) as pool:
            futures = [pool.submit(fetch, e) for e in expirations]
            fetched = [f.result() for f in futures]

        results, chains, failed, seen_dates = [], [], [], set()
        for expiration, chain, error in fetched:
            if chain is None:
                failed.append(expiration["date"])
                continue
            # The provider resolves a dte to the closest listing; two dtes can
            # land on the same chain.
            if chain.get("expirationDate") in seen_dates:
                continue
            seen_dates.add(chain.get("expirationDate"))
            chains.append(chain)
            results.append(strategy_builder.build(strategy, params, chain, target))
        if not chains:
            return None

        combined = strategy_builder.combine(strategy, results)
        if failed:
            combined["reasons"].append(f"Couldn't load {len(failed)} expiration(s): {', '.join(failed)}")
        best = combined["best"]
        lead = next((c for c in chains if best and c.get("expirationDate") == best["expirationDate"]), chains[0])
        return {
            "symbol": symbol,
            "strategy": strategy,
            "spot": lead["spot"],
            "iv": lead.get("iv"),
            "dte": lead.get("dte"),
            "expirationDate": lead.get("expirationDate"),
            "expirationsSearched": len(chains),
            **combined,
        }

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
        "CALL" rank single contracts to sell (fields below); "LONG_PUT" /
        "LONG_CALL" rank single contracts to *buy*, by leverage — see the
        long-option fields further down; "RATIO_PUT" /
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

        For LONG_PUT / LONG_CALL rows instead (bought at the ask; ROI's
        "unchanged price" premise doesn't fit a long option, which loses
        its time value if nothing moves):
          premium            the ask — what a buy order can fill at; also
                             the max loss.
          leverage           lambda = |delta| * spot / ask: roughly the
                             option's % change for a 1% move in the stock.
                             This is the sort key (highest first); None if
                             delta didn't come back, sorted last.
          breakeven          call: strike + ask; put: strike - ask.
          breakevenMovePct   % the stock must move in the option's favor by
                             expiration to break even.

        A ticker that fails to load (bad symbol, no listed options, broker
        hiccup) is reported in "errors" rather than failing the whole screen.
        """
        option_types = STRATEGY_OPTION_TYPES[strategy]

        def fetch(symbol: str):
            try:
                return symbol, self.option_chain_provider.get_screener_contracts(
                    symbol, min_dte, max_dte, option_types, min_otm_pct, max_otm_pct
                ), None
            except Exception as e:
                logger.error("Screener failed for %s: %s", symbol, e)
                if getattr(e, "status_code", None) == 404:
                    return symbol, None, "Symbol not found, or it has no listed options"
                return symbol, None, str(e) or e.__class__.__name__

        # Market data never touches Schwab (only Tastytrade), so these
        # threads don't need the request's per-user context. Code that adds a
        # Schwab call to a thread pool must submit via
        # contextvars.copy_context().run — see AGENTS.md.
        with ThreadPoolExecutor(max_workers=min(_SCREENER_WORKERS, len(symbols) or 1)) as pool:
            futures = [pool.submit(fetch, s) for s in symbols]
            results = [f.result() for f in futures]

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
                if strategy in LONG_STRATEGIES:
                    row = self._long_option_row(c, symbol, spot)
                    if row and delta_ok(c):
                        rows.append(row)
                    continue
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
                errors.append({"symbol": symbol, "message": "No contracts with a live quote matched the delta range"
                               if delta_filter_on else "No contracts with a live quote in the selected range"})

        if strategy in LONG_STRATEGIES:
            rows.sort(key=lambda r: (r["leverage"] is not None, r["leverage"] or 0), reverse=True)
        else:
            rows.sort(key=lambda r: r["annualizedRoi"], reverse=True)
        return {
            "results": rows[:limit],
            "totalMatches": len(rows),
            "errors": errors,
            "truncated": truncated,
        }

    @staticmethod
    def _long_option_row(c: dict, underlying: str, spot: float) -> Optional[dict]:
        """A screener row for *buying* contract `c` (see screen_options'
        LONG_PUT/LONG_CALL fields), or None if it has no ask to buy at."""
        ask, dte = c["ask"], c["dte"]
        if not ask or ask <= 0 or dte is None:
            return None
        strike, bid = c["strike"], c["bid"]
        if c["type"] == "CALL":
            breakeven = strike + ask
            move = (breakeven - spot) / spot * 100
        else:
            breakeven = strike - ask
            move = (spot - breakeven) / spot * 100
        return {
            **c,
            "strategy": f"LONG_{c['type']}",
            "underlying": underlying,
            "spot": spot,
            "mid": (bid + ask) / 2 if bid else None,
            "otmPct": otm_pct(strike, spot, c["type"]),
            "premium": ask,
            "leverage": abs(c["delta"]) * spot / ask if c["delta"] is not None else None,
            "breakeven": breakeven,
            "breakevenMovePct": move,
        }

