"""Multi-leg strategy builders for the Options Screener
(MarketService.screen_options).

Each builder takes one expiration's contracts for one underlying (already
limited to the moneyness band by the chain provider) and returns every
qualifying combination as a screener row, priced conservatively: short legs
at the bid, long legs at the ask — what a combo order can realistically fill
at, consistent with single-leg rows being priced at the bid.

Strategy definitions:

  RATIO_PUT     1x2 put ratio spread, same rules as
                copilot/skills/put_ratio_spread.md: buy 1 put at a higher
                strike, sell 2 puts at a strictly lower strike, and it must
                open for a net credit (2 x short bid - long ask > 0).

  JADE_LIZARD   sell 1 put + sell a call spread (sell 1 call, buy 1 call at
                a higher strike), put strike below the short call, and total
                credit >= the call spread's width — the defining property:
                no risk to the upside, only the short put's downside.

Both carry naked-put-style downside (losing $1 per share for each $1 the
stock falls below the lower breakeven), so capital is the max loss if the
stock goes to zero — the cash it takes to fully secure the position — and
ROI follows the single-leg convention: P&L if the underlying is unchanged at
expiration, divided by capital.
"""

from typing import Callable, Optional

from service.strategy_math import net_premium, payoff, payoff_profile

# Widest call spread considered for a jade lizard, in strike steps above the
# short call. Wings are typically narrow (the credit has to cover the
# width), and capping this keeps the search at puts x calls x 5 per
# expiration rather than puts x calls^2.
JADE_MAX_WING_STRIKES = 5

# "PUT"/"CALL" are single contracts to *sell* (short); "LONG_PUT"/
# "LONG_CALL" single contracts to *buy*, ranked by leverage rather than ROI
# (see MarketService.screen_options).
STRATEGIES = ("PUT", "CALL", "LONG_PUT", "LONG_CALL", "RATIO_PUT", "JADE_LIZARD")
MULTI_LEG_STRATEGIES = ("RATIO_PUT", "JADE_LIZARD")
LONG_STRATEGIES = ("LONG_PUT", "LONG_CALL")
# Which option types each strategy needs fetched.
STRATEGY_OPTION_TYPES = {
    "PUT": ["PUT"],
    "CALL": ["CALL"],
    "LONG_PUT": ["PUT"],
    "LONG_CALL": ["CALL"],
    "RATIO_PUT": ["PUT"],
    "JADE_LIZARD": ["PUT", "CALL"],
}


def _leg(contract: dict, qty: int) -> dict:
    """qty is signed: positive = bought, negative = sold."""
    return {
        "symbol": contract["symbol"],
        "type": contract["type"],
        "strike": contract["strike"],
        "qty": qty,
        "price": contract["ask"] if qty > 0 else contract["bid"],
        "bid": contract["bid"],
        "ask": contract["ask"],
        "delta": contract["delta"],
    }


def _position_row(strategy: str, underlying: str, spot: float, legs: list[dict]) -> Optional[dict]:
    credit = net_premium(legs)
    capital = -payoff(legs, credit, 0.0)
    if capital <= 0:
        # No downside loss even at zero — only possible for a degenerate
        # strike combination; nothing meaningful to rank it against.
        return None

    # Both screener strategies carry no net short calls, so max profit is
    # always bounded (see strategy_math.payoff_profile).
    profile = payoff_profile(legs, credit)
    breakevens = profile["breakevens"]

    dte = legs[0]["dte"]
    roi = payoff(legs, credit, spot) / capital
    short_deltas = [abs(leg["delta"]) for leg in legs if leg["qty"] < 0 and leg["delta"] is not None]
    return {
        # Unique per combination — used as the row's selection key.
        "symbol": "|".join(f'{leg["qty"]}:{leg["symbol"]}' for leg in legs),
        "strategy": strategy,
        "underlying": underlying,
        "spot": spot,
        "expirationDate": legs[0]["expirationDate"],
        "dte": dte,
        "legs": [{k: v for k, v in leg.items() if k not in ("dte", "expirationDate")} for leg in legs],
        "credit": credit,
        "maxProfit": profile["maxProfit"],
        "capital": capital,
        "breakevens": breakevens,
        "lowerBreakeven": breakevens[0] if breakevens else None,
        "shortDelta": max(short_deltas) if short_deltas else None,
        "roi": roi * 100,
        # Same max(dte, 1) convention as single-leg rows.
        "annualizedRoi": roi * 365 / max(dte, 1) * 100,
    }


def _with_expiry(leg: dict, contract: dict) -> dict:
    return {**leg, "dte": contract["dte"], "expirationDate": contract["expirationDate"]}


def ratio_put_rows(
    underlying: str, spot: float, contracts: list[dict], short_ok: Callable[[dict], bool]
) -> list[dict]:
    """Every 1x2 put ratio spread (long higher strike, 2 short at a strictly
    lower strike, net credit) within one expiration's `contracts`.
    `short_ok` applies the screener's delta filter to the short leg."""
    puts = sorted((c for c in contracts if c["type"] == "PUT"), key=lambda c: c["strike"])
    longs = [c for c in puts if c["ask"] and c["ask"] > 0]
    shorts = [c for c in puts if c["bid"] and c["bid"] > 0 and short_ok(c)]
    rows = []
    for long in longs:
        for short in shorts:
            if short["strike"] >= long["strike"]:
                break  # sorted by strike — every later short is too high as well
            if 2 * short["bid"] - long["ask"] <= 0:
                continue
            legs = [_with_expiry(_leg(long, 1), long), _with_expiry(_leg(short, -2), short)]
            row = _position_row("RATIO_PUT", underlying, spot, legs)
            if row:
                rows.append(row)
    return rows


def jade_lizard_rows(
    underlying: str, spot: float, contracts: list[dict], short_ok: Callable[[dict], bool]
) -> list[dict]:
    """Every jade lizard (short put below a short call spread no wider than
    JADE_MAX_WING_STRIKES strikes, total credit >= spread width) within one
    expiration's `contracts`. `short_ok` applies the screener's delta filter
    to the two short legs."""
    puts = [c for c in contracts if c["type"] == "PUT" and c["bid"] and c["bid"] > 0 and short_ok(c)]
    calls = sorted((c for c in contracts if c["type"] == "CALL"), key=lambda c: c["strike"])
    rows = []
    for i, short_call in enumerate(calls):
        if not short_call["bid"] or short_call["bid"] <= 0 or not short_ok(short_call):
            continue
        for long_call in calls[i + 1 : i + 1 + JADE_MAX_WING_STRIKES]:
            if not long_call["ask"] or long_call["ask"] <= 0:
                continue
            width = long_call["strike"] - short_call["strike"]
            spread_credit = short_call["bid"] - long_call["ask"]
            for put in puts:
                if put["strike"] >= short_call["strike"]:
                    continue
                if put["bid"] + spread_credit < width:
                    continue  # upside risk left — not a jade lizard
                legs = [
                    _with_expiry(_leg(put, -1), put),
                    _with_expiry(_leg(short_call, -1), short_call),
                    _with_expiry(_leg(long_call, 1), long_call),
                ]
                row = _position_row("JADE_LIZARD", underlying, spot, legs)
                if row:
                    rows.append(row)
    return rows


STRATEGY_BUILDERS = {"RATIO_PUT": ratio_put_rows, "JADE_LIZARD": jade_lizard_rows}
