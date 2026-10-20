"""The Options Screener: rank every contract (or multi-leg combination)
across several tickers by what it returns."""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from service.market.chain_providers import OptionChainProvider
from service.market.errors import MarketDataError, SymbolNotFound
from service.market.screener_strategies import (
    LONG_STRATEGIES,
    SCREENER_TEMPLATES,
    STRATEGY_OPTION_TYPES,
    combo_rows,
)
from service.shared.strategy_math import otm_pct

logger = logging.getLogger(__name__)

# Tickers screened concurrently — each is a chain fetch plus a DXLink
# snapshot, mostly spent waiting on the network, so a small pool cuts a
# 10-ticker screen from ~10 sequential round-trips to ~3 without hammering
# Tastytrade. Market code only calls Tastytrade, so these threads don't need
# the request's per-user context (a Schwab call would — see AGENTS.md).
WORKERS = 4


def short_option_row(c: dict, underlying: str, spot: float) -> Optional[dict]:
    """A row for *selling* contract `c`, or None without a bid to sell at.

      premium        the bid — what a sell order can fill at right now.
      capital        cash-secured put: strike; covered call: spot (the 100
                     shares). Per share, like premium.
      roi            (premium - intrinsic) / capital — the return if the
                     underlying is unchanged at expiration. An ITM strike's
                     intrinsic part is handed straight back on assignment,
                     so it's not counted as return.
      annualizedRoi  roi * 365 / dte (0-DTE counts as one day) — the sort key.
      breakeven      put: strike - premium; call: spot - premium.
    """
    bid, ask, dte, strike = c["bid"], c["ask"], c["dte"], c["strike"]
    if not bid or bid <= 0 or dte is None:
        return None
    if c["type"] == "PUT":
        capital, intrinsic, breakeven = strike, max(strike - spot, 0), strike - bid
    else:
        capital, intrinsic, breakeven = spot, max(spot - strike, 0), spot - bid
    roi = (bid - intrinsic) / capital
    return {
        **c,
        "strategy": c["type"],
        "underlying": underlying,
        "spot": spot,
        "mid": (bid + ask) / 2 if ask else None,
        "otmPct": otm_pct(strike, spot, c["type"]),
        "premium": bid,
        "capital": capital,
        "roi": roi * 100,
        "annualizedRoi": roi * 365 / max(dte, 1) * 100,
        "breakeven": breakeven,
    }


def long_option_row(c: dict, underlying: str, spot: float) -> Optional[dict]:
    """A row for *buying* contract `c`, or None without an ask to buy at.
    ROI's "unchanged price" premise doesn't fit a long option, so instead:

      premium           the ask — the fill, and the max loss.
      leverage          |delta| * spot / ask: roughly the option's % change
                        for a 1% move in the stock. The sort key; None if
                        delta didn't come back (sorted last).
      breakeven         call: strike + ask; put: strike - ask.
      breakevenMovePct  % the stock must move in the option's favor by
                        expiration to break even.
    """
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


def screen_options(
    provider: OptionChainProvider,
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
    """Rank every put/call (or multi-leg combination) across `symbols` in
    the DTE and moneyness window, best first. `strategy` is one of
    screener_strategies.STRATEGIES: PUT/CALL rank contracts to sell by
    annualized ROI (short_option_row), LONG_PUT/LONG_CALL contracts to buy by
    leverage (long_option_row), and SCREENER_TEMPLATES multi-leg
    combinations built within each expiration (screener_strategies.py) —
    for those, every leg must sit inside the moneyness band and the delta
    filter applies to the legs being sold.

    The delta bounds filter on |delta|, so one range covers both sides; with
    either bound set, a contract whose delta didn't come back is excluded.

    A ticker that fails (bad symbol, nothing listed, broker hiccup) is
    reported in "errors" rather than failing the whole screen.
    """
    option_types = STRATEGY_OPTION_TYPES[strategy]

    def fetch(symbol: str):
        try:
            return symbol, provider.get_screener_contracts(
                symbol, min_dte, max_dte, option_types, min_otm_pct, max_otm_pct
            ), None
        except SymbolNotFound:
            return symbol, None, "Symbol not found, or it has no listed options"
        except MarketDataError as e:
            return symbol, None, str(e)
        except Exception as e:  # never let one ticker sink the screen, nor leak internals
            logger.exception("Screener failed for %s: %s", symbol, e)
            return symbol, None, MarketDataError().args[0]

    with ThreadPoolExecutor(max_workers=min(WORKERS, len(symbols) or 1)) as pool:
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
        if result["truncated"]:
            truncated.append(symbol)
        rows_before = len(rows)
        spot = result["spot"]

        if strategy in SCREENER_TEMPLATES:
            by_expiration: dict[str, list[dict]] = {}
            for c in result["contracts"]:
                if c["dte"] is not None:
                    by_expiration.setdefault(c["expirationDate"], []).append(c)
            for contracts in by_expiration.values():
                combos, trimmed = combo_rows(strategy, symbol, spot, contracts, delta_ok)
                rows.extend(combos)
                if trimmed and symbol not in truncated:
                    truncated.append(symbol)
            if len(rows) == rows_before:
                errors.append({"symbol": symbol, "message": "No qualifying combinations in the selected range"
                               + (" and delta range" if delta_filter_on else "")})
            continue

        make_row = long_option_row if strategy in LONG_STRATEGIES else short_option_row
        for c in result["contracts"]:
            row = make_row(c, symbol, spot)
            if row and delta_ok(c):
                rows.append(row)
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
