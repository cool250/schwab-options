"""Expiration payoff math for multi-leg option positions, shared by the
Options Screener's strategy builders (service/market/screener_strategies.py) and
the Analyze page's Strategy Builder (service/market/strategy_builder.py).

A leg here is a dict with at least "type" ("PUT"/"CALL"), "strike", and a
signed "qty" (positive = bought, negative = sold). Every figure is per share
of one unit of the position — callers scale by contract multiplier and
quantity themselves.

The payoff at expiration is piecewise linear with kinks only at the strikes,
so everything (max profit/loss, breakevens, probability of profit) is found
exactly by evaluating the kinks plus the slope past the highest strike —
no price-grid sampling.
"""

import math
from typing import Optional


def intrinsic(option_type: str, strike: float, price: float) -> float:
    return max(strike - price, 0.0) if option_type == "PUT" else max(price - strike, 0.0)


def payoff(legs: list[dict], credit: float, price: float) -> float:
    """Per-share P&L at expiration with the underlying at `price`.
    `credit` is the net premium received (negative for a net debit)."""
    return credit + sum(leg["qty"] * intrinsic(leg["type"], leg["strike"], price) for leg in legs)


def net_premium(legs: list[dict]) -> float:
    """Net credit per share at each leg's "price" (negative = net debit)."""
    return sum(-leg["qty"] * leg["price"] for leg in legs)


def payoff_profile(legs: list[dict], credit: float) -> dict:
    """Max profit, max loss and breakevens of the expiration payoff.

    Returns {"points", "values", "upsideSlope", "maxProfit", "maxLoss",
    "breakevens"}. maxProfit/maxLoss are None when unbounded (P&L keeps
    growing/falling past the highest strike — only net long/short calls
    can do that; the downside always stops at a price of zero).
    """
    strikes = sorted({leg["strike"] for leg in legs})
    points = [0.0, *strikes]
    values = [payoff(legs, credit, p) for p in points]
    # Past the highest strike every put is worthless and every call gains
    # $1 per $1 of price, so the slope there is just the net call quantity.
    upside_slope = sum(leg["qty"] for leg in legs if leg["type"] == "CALL")

    breakevens = []
    for (p1, v1), (p2, v2) in zip(zip(points, values), zip(points[1:], values[1:])):
        if (v1 < 0 <= v2 or v1 >= 0 > v2) and v1 != v2:
            breakevens.append(p1 + (p2 - p1) * (-v1) / (v2 - v1))
    last = values[-1]
    if upside_slope and (last < 0 < upside_slope or last > 0 > upside_slope):
        breakevens.append(points[-1] - last / upside_slope)

    return {
        "points": points,
        "values": values,
        "upsideSlope": upside_slope,
        "maxProfit": None if upside_slope > 0 else max(values),
        "maxLoss": None if upside_slope < 0 else min(values),
        "breakevens": breakevens,
    }


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def probability_of_profit(
    legs: list[dict], credit: float, spot: float, iv: Optional[float], dte: int
) -> Optional[float]:
    """Chance the position finishes above zero P&L at expiration, under a
    driftless lognormal model at volatility `iv` (a fraction, e.g. 0.25).
    An estimate — one flat IV, no skew, no early exit — but it applies to any
    leg combination, unlike a single short-delta rule of thumb.
    Returns None without a usable IV or spot."""
    if not iv or iv <= 0 or not spot or spot <= 0:
        return None
    profile = payoff_profile(legs, credit)
    sigma = iv * math.sqrt(max(dte, 0.5) / 365)

    def cdf(price: float) -> float:
        if price <= 0:
            return 0.0
        return _norm_cdf((math.log(price / spot) + sigma * sigma / 2) / sigma)

    # The breakevens split the price axis into regions of constant sign;
    # test each region's sign at an interior point.
    edges = [0.0, *sorted(profile["breakevens"]), math.inf]
    top = profile["points"][-1]
    pop = 0.0
    for lo, hi in zip(edges, edges[1:]):
        probe = (lo + hi) / 2 if hi != math.inf else max(lo, top) * 1.5 + 1
        if payoff(legs, credit, probe) > 0:
            pop += (1.0 if hi == math.inf else cdf(hi)) - cdf(lo)
    return pop
