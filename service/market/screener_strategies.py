"""Multi-leg strategies for the Options Screener (service/market/screener.py).

A screener strategy IS a Strategy Builder template
(strategy_builder.TEMPLATES): enumerate_combinations() lists every placement
of its legs within one expiration's contracts (already limited to the
moneyness band), and each is priced conservatively — short legs at the bid,
long legs at the ask, what a combo order can realistically fill at,
consistent with single-leg rows at the bid. The template's own rules apply
at those prices: it must open for a net credit, and creditCoversWing
(the jade lizard's "no upside risk") is checked against the natural credit.

Every multi-leg *credit* template is a screener strategy — SCREENER_TEMPLATES
is generated from TEMPLATES, so a strategy added to the Strategy Builder
shows up here too, under the same name. (Single-leg Short Put / Short Call
are the screener's own PUT / CALL rows; debit templates aren't screened.)

ROI follows the single-leg convention: P&L if the underlying is unchanged at
expiration, divided by capital — what it takes to fully secure the
position (see position_capital).
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
# Most combinations searched per template per expiration. Within budget,
# every contract in the band is tried; over it (an iron condor on a wide
# band: puts x calls x 5 x 5 — ~3s per expiration at 120 strikes a side),
# each anchor's strikes are trimmed to the ones nearest spot, which carry
# the premium, and the ticker is reported as truncated.
COMBO_BUDGET = 25_000

# "PUT"/"CALL" are single contracts to *sell* (short); "LONG_PUT"/
# "LONG_CALL" single contracts to *buy*, ranked by leverage rather than ROI
# (see MarketService.screen_options).
SINGLE_LEG_NAMES = {"PUT": "Short Puts", "CALL": "Short Calls", "LONG_PUT": "Long Puts", "LONG_CALL": "Long Calls"}
LONG_STRATEGIES = ("LONG_PUT", "LONG_CALL")
# Multi-leg screener strategies: every multi-leg credit template, in the
# Strategy Builder's order.
SCREENER_TEMPLATES = tuple(
    key for key, t in TEMPLATES.items() if t["direction"] == "credit" and len(t["legs"]) > 1
)
STRATEGIES = (*SINGLE_LEG_NAMES, *SCREENER_TEMPLATES)
# Which option types each strategy needs fetched.
STRATEGY_OPTION_TYPES = {
    "PUT": ["PUT"],
    "CALL": ["CALL"],
    "LONG_PUT": ["PUT"],
    "LONG_CALL": ["CALL"],
    **{
        key: [t for t in ("PUT", "CALL") if any(leg["type"] == t for leg in TEMPLATES[key]["legs"])]
        for key in SCREENER_TEMPLATES
    },
}


def list_strategies() -> list[dict]:
    """The screener's strategy choices, for its dropdown: {id, name, kind},
    kind = "short" / "long" (single contracts) or "combo" (a template)."""
    singles = [
        {"id": key, "name": name, "kind": "long" if key in LONG_STRATEGIES else "short"}
        for key, name in SINGLE_LEG_NAMES.items()
    ]
    return singles + [{"id": key, "name": TEMPLATES[key]["name"], "kind": "combo"} for key in SCREENER_TEMPLATES]


def position_capital(profile: dict, spot: float) -> float:
    """Capital to fully secure a position, per share, from its payoff_profile:

      bounded risk     the max loss (a spread's width less the credit; a
                       ratio put's loss if the stock goes to zero)
      unlimited upside the downside loss (if any) plus spot for each net
                       short call — the shares that would cover them, same
                       as a single Short Call's capital of spot
    """
    if profile["maxLoss"] is not None:
        return -profile["maxLoss"]
    uncovered_calls = max(-profile["upsideSlope"], 0)
    return max(-min(profile["values"]), 0.0) + uncovered_calls * spot


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
    # Credit templates are never net long calls, so max profit is always
    # bounded (see strategy_math.payoff_profile).
    profile = payoff_profile(legs, credit)
    capital = position_capital(profile, spot)
    if capital <= 0:
        # No loss anywhere — only possible for a degenerate strike
        # combination; nothing meaningful to rank it against.
        return None
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


def _trim_to_budget(template: dict, spot: float, contracts: list[dict]) -> tuple[list[dict], bool]:
    """Keep the strikes nearest spot (per option type) when searching every
    contract would exceed COMBO_BUDGET combinations. (contracts, trimmed)."""
    anchors = [s for s in template["legs"] if s["role"] == "anchor"]
    wing_factor = MAX_WING_STEPS ** sum(s["role"] == "wing" for s in template["legs"])
    by_type = {t: [c for c in contracts if c["type"] == t] for t in ("PUT", "CALL")}
    estimate = wing_factor
    for spec in anchors:
        estimate *= len(by_type[spec["type"]])
    if estimate <= COMBO_BUDGET:
        return contracts, False
    keep = max(int((COMBO_BUDGET / wing_factor) ** (1 / len(anchors))), 1)
    trimmed = []
    for t, group in by_type.items():
        near = sorted(group, key=lambda c: abs(c["strike"] - spot))
        # Wings sit beyond their anchor, so keep a few extra strikes for them.
        trimmed.extend(near[: keep + MAX_WING_STEPS] if wing_factor > 1 else near[:keep])
    return trimmed, True


def combo_rows(
    strategy: str, underlying: str, spot: float, contracts: list[dict], sell_ok: Callable[[dict], bool]
) -> tuple[list[dict], bool]:
    """Every qualifying combination of template `strategy` within one
    expiration's `contracts`, as screener rows, and whether the search was
    trimmed to COMBO_BUDGET. `sell_ok` applies the screener's delta filter to
    the legs being sold."""
    template = TEMPLATES[strategy]
    covers = template.get("creditCoversWing")
    contracts, trimmed = _trim_to_budget(template, spot, contracts)
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
    return rows, trimmed
