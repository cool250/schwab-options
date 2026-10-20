"""Multi-leg strategies for the Options Screener (service/market/screener.py).

A screener strategy IS a Strategy Builder template
(strategy_builder.TEMPLATES): enumerate_combinations() lists every placement
of its legs within one expiration's contracts (already limited to the
moneyness band), and each is priced conservatively — short legs at the bid,
long legs at the ask, what a combo order can realistically fill at,
consistent with single-leg rows at the bid. The template's own rules apply
at those prices: it must open for a net credit, and creditCoversWing
(the jade lizard's "no upside risk") is checked against the natural credit.

  RATIO_PUT     buy 1 put, sell 2 puts at a strictly lower strike.
  JADE_LIZARD   sell 1 put + a call spread (wing within MAX_WING_STEPS
                listed strikes), put below the short call.

Adding one = adding its template id to SCREENER_TEMPLATES (and to
STRATEGIES / STRATEGY_OPTION_TYPES), provided its risk is to the downside:
capital is the max loss if the stock goes to zero — the cash it takes to
fully secure the position — and ROI follows the single-leg convention: P&L
if the underlying is unchanged at expiration, divided by capital. A
template with no loss at zero (e.g. a call spread) produces no rows.
"""

from typing import Callable, Optional

from service.market.strategy_builder import TEMPLATES, enumerate_combinations
from service.shared.strategy_math import net_premium, payoff, payoff_profile

# Widest call spread considered for a jade lizard, in strike steps above the
# short call. Wings are typically narrow (the credit has to cover the
# width), and capping this keeps the search at puts x calls x 5 per
# expiration rather than puts x calls^2.
# Furthest a wing may sit from its leg, in listed strikes.
MAX_WING_STEPS = 5

# "PUT"/"CALL" are single contracts to *sell* (short); "LONG_PUT"/
# "LONG_CALL" single contracts to *buy*, ranked by leverage rather than ROI
# (see MarketService.screen_options).
STRATEGIES = ("PUT", "CALL", "LONG_PUT", "LONG_CALL", "RATIO_PUT", "JADE_LIZARD")
# Multi-leg screener strategies, each a strategy_builder template id.
SCREENER_TEMPLATES = ("RATIO_PUT", "JADE_LIZARD")
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


def combo_rows(
    strategy: str, underlying: str, spot: float, contracts: list[dict], sell_ok: Callable[[dict], bool]
) -> list[dict]:
    """Every qualifying combination of template `strategy` within one
    expiration's `contracts`, as screener rows. `sell_ok` applies the
    screener's delta filter to the legs being sold."""
    template = TEMPLATES[strategy]
    covers = template.get("creditCoversWing")
    rows = []
    for combo in enumerate_combinations(strategy, contracts, sell_ok, MAX_WING_STEPS):
        legs = [{**_leg(c, c["qty"]), "dte": c["dte"], "expirationDate": c["expirationDate"]} for c in combo]
        credit = net_premium(legs)
        if template["direction"] == "credit" and credit <= 0:
            continue
        if covers:
            by_key = {c["key"]: c for c in combo}
            if credit < abs(by_key[covers[1]]["strike"] - by_key[covers[0]]["strike"]):
                continue  # upside risk left — not a jade lizard
        row = _position_row(strategy, underlying, spot, legs)
        if row:
            rows.append(row)
    return rows
