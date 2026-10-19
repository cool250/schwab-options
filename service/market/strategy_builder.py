"""Strategy Builder for the Analyze page (MarketService.build_strategy).

The user picks a strategy template and how to place its legs (target delta,
% OTM, expected move, wing width, …); this module turns that into real
contracts from one expiration's live chain and prices the result at mid.

Template vocabulary — each leg spec is one of three roles:

  anchor   placed directly from user parameters, by one of ANCHOR_MODES
  wing     placed relative to another leg ("of"), on a given side
           ("dir": +1 = higher strike, -1 = lower), by one of WING_MODES
  same     same strike as another leg ("of"), opposite option type —
           the second half of a straddle / iron-fly body

`qty` is signed per unit of the position (positive = bought, negative =
sold). Every template has a direction: "credit" templates must open for a
net credit at mid, "debit" ones for a net debit. Extra per-template rules:

  order        list of (leg_a, leg_b): leg_a's strike must be strictly
               below leg_b's (e.g. a strangle's put below its call)
  creditCoversWing  (leg, wing): net credit >= that call spread's width —
               the jade lizard's "no upside risk" property, same rule as
               the screener's jade_lizard_rows

Adding a strategy = adding a TEMPLATES entry; the solver and the frontend
form (built from GET /api/market/strategies) need no changes.

Solver: place every anchor from its parameters, then search each anchor
±SEARCH_STEPS listed strikes around that placement (wings keep their own
rule relative to the moved anchor). Every combination that passes the
template's rules is a candidate; candidates are ranked by how far their
anchors moved from the requested placement (fewest total steps first), then
by the better premium. The search is small — at most (2*5+1)^2 = 121
combinations for a two-anchor template — so it's brute force, like the
screener's builders.
"""

import math
from typing import Optional

from service.market.chain_providers import otm_pct
from service.shared.strategy_math import net_premium, payoff, payoff_profile, probability_of_profit

ANCHOR_MODES = ("atm", "delta", "otm_pct", "sigma", "strike")
WING_MODES = ("width", "steps", "delta", "otm_pct")
SEARCH_STEPS = 5
MAX_ALTERNATIVES = 5
# An expiration range is solved per listed expiration (one live chain fetch
# each, ~2-3s), so it's capped; the frontend only offers ranges this wide.
MAX_RANGE_EXPIRATIONS = 10
# Alternatives shown for a range: the best match on each other expiration
# first, then the winning expiration's own runners-up.
MAX_RANGE_ALTERNATIVES = 8
# Strikes fetched per side of ATM. Wide enough that ~5Δ legs and their
# wings are in the window on index/ETF chains with $1 strikes.
STRIKE_COUNT = 60


def _anchor(key, type_, qty, label, mode, value=None):
    return {"key": key, "role": "anchor", "type": type_, "qty": qty, "label": label,
            "default": {"mode": mode, "value": value}}


def _wing(key, type_, qty, label, of, direction, mode, value):
    return {"key": key, "role": "wing", "type": type_, "qty": qty, "label": label,
            "of": of, "dir": direction, "default": {"mode": mode, "value": value}}


def _same(key, type_, qty, label, of):
    return {"key": key, "role": "same", "type": type_, "qty": qty, "label": label, "of": of}


TEMPLATES: dict[str, dict] = {
    # ---------------- net credit ----------------
    "SHORT_PUT": {
        "name": "Short Put", "direction": "credit",
        "description": "Sell one put below the market; keep the premium if it expires above the strike.",
        "legs": [_anchor("short_put", "PUT", -1, "Short put", "delta", 0.30)],
    },
    "SHORT_CALL": {
        "name": "Short Call", "direction": "credit",
        "description": "Sell one call above the market; unlimited risk to the upside.",
        "legs": [_anchor("short_call", "CALL", -1, "Short call", "delta", 0.30)],
    },
    "PUT_CREDIT_SPREAD": {
        "name": "Put Credit Spread", "direction": "credit",
        "description": "Sell a put and buy a lower put — a short put with capped risk.",
        "legs": [
            _anchor("short_put", "PUT", -1, "Short put", "delta", 0.30),
            _wing("long_put", "PUT", 1, "Long put (wing)", "short_put", -1, "width", 5),
        ],
    },
    "CALL_CREDIT_SPREAD": {
        "name": "Call Credit Spread", "direction": "credit",
        "description": "Sell a call and buy a higher call — a short call with capped risk.",
        "legs": [
            _anchor("short_call", "CALL", -1, "Short call", "delta", 0.30),
            _wing("long_call", "CALL", 1, "Long call (wing)", "short_call", 1, "width", 5),
        ],
    },
    "SHORT_STRANGLE": {
        "name": "Strangle", "direction": "credit",
        "description": "Sell an OTM put and an OTM call; profits if the stock stays between them.",
        "legs": [
            _anchor("short_put", "PUT", -1, "Short put", "delta", 0.16),
            _anchor("short_call", "CALL", -1, "Short call", "delta", 0.16),
        ],
        "order": [("short_put", "short_call")],
    },
    "SHORT_STRADDLE": {
        "name": "Straddle", "direction": "credit",
        "description": "Sell a put and a call at the same strike, usually at the money.",
        "legs": [
            _anchor("short_put", "PUT", -1, "Short strike", "atm"),
            _same("short_call", "CALL", -1, "Short call", "short_put"),
        ],
    },
    "IRON_CONDOR": {
        "name": "Iron Condor", "direction": "credit",
        "description": "A put credit spread below the market plus a call credit spread above it.",
        "legs": [
            _wing("long_put", "PUT", 1, "Long put (wing)", "short_put", -1, "width", 5),
            _anchor("short_put", "PUT", -1, "Short put", "delta", 0.16),
            _anchor("short_call", "CALL", -1, "Short call", "delta", 0.16),
            _wing("long_call", "CALL", 1, "Long call (wing)", "short_call", 1, "width", 5),
        ],
        "order": [("short_put", "short_call")],
    },
    "IRON_BUTTERFLY": {
        "name": "Iron Butterfly", "direction": "credit",
        "description": "A short straddle with protective wings on both sides.",
        "legs": [
            _wing("long_put", "PUT", 1, "Long put (wing)", "short_put", -1, "width", 10),
            _anchor("short_put", "PUT", -1, "Short strike", "atm"),
            _same("short_call", "CALL", -1, "Short call", "short_put"),
            _wing("long_call", "CALL", 1, "Long call (wing)", "short_call", 1, "width", 10),
        ],
    },
    "JADE_LIZARD": {
        "name": "Jade Lizard", "direction": "credit",
        "description": "Short put plus a call credit spread, with total credit covering the call spread — no upside risk.",
        "legs": [
            _anchor("short_put", "PUT", -1, "Short put", "delta", 0.30),
            _anchor("short_call", "CALL", -1, "Short call", "delta", 0.20),
            # Narrow by default (one listed strike): the total credit has to cover
            # the call spread's width, which a $5 wing rarely allows near 20-30Δ.
            _wing("long_call", "CALL", 1, "Long call (wing)", "short_call", 1, "steps", 1),
        ],
        "order": [("short_put", "short_call")],
        "creditCoversWing": ("short_call", "long_call"),
    },
    "RATIO_PUT": {
        "name": "Ratio Put (1×2)", "direction": "credit",
        "description": "Buy one put and sell two lower puts for a net credit.",
        "legs": [
            _anchor("long_put", "PUT", 1, "Long put", "delta", 0.30),
            _anchor("short_put", "PUT", -2, "Short puts (×2)", "delta", 0.15),
        ],
        "order": [("short_put", "long_put")],
    },
    # ---------------- net debit ----------------
    "LONG_CALL": {
        "name": "Long Call", "direction": "debit",
        "description": "Buy one call; risk is limited to the premium paid.",
        "legs": [_anchor("long_call", "CALL", 1, "Long call", "delta", 0.50)],
    },
    "LONG_PUT": {
        "name": "Long Put", "direction": "debit",
        "description": "Buy one put; risk is limited to the premium paid.",
        "legs": [_anchor("long_put", "PUT", 1, "Long put", "delta", 0.50)],
    },
    "CALL_DEBIT_SPREAD": {
        "name": "Call Debit Spread", "direction": "debit",
        "description": "Buy a call and sell a higher call to cheapen it — capped profit, capped risk.",
        "legs": [
            _anchor("long_call", "CALL", 1, "Long call", "delta", 0.50),
            _wing("short_call", "CALL", -1, "Short call", "long_call", 1, "width", 5),
        ],
    },
    "PUT_DEBIT_SPREAD": {
        "name": "Put Debit Spread", "direction": "debit",
        "description": "Buy a put and sell a lower put to cheapen it — capped profit, capped risk.",
        "legs": [
            _anchor("long_put", "PUT", 1, "Long put", "delta", 0.50),
            _wing("short_put", "PUT", -1, "Short put", "long_put", -1, "width", 5),
        ],
    },
    "LONG_STRADDLE": {
        "name": "Long Straddle", "direction": "debit",
        "description": "Buy a put and a call at the same strike; profits from a big move either way.",
        "legs": [
            _anchor("long_put", "PUT", 1, "Long strike", "atm"),
            _same("long_call", "CALL", 1, "Long call", "long_put"),
        ],
    },
    "LONG_STRANGLE": {
        "name": "Long Strangle", "direction": "debit",
        "description": "Buy an OTM put and an OTM call; cheaper than a straddle, needs a bigger move.",
        "legs": [
            _anchor("long_put", "PUT", 1, "Long put", "delta", 0.25),
            _anchor("long_call", "CALL", 1, "Long call", "delta", 0.25),
        ],
        "order": [("long_put", "long_call")],
    },
}


class StrategyParamError(ValueError):
    """Bad template/parameter input — the API maps this to a 422."""


def list_templates() -> list[dict]:
    return [
        {
            "id": key,
            "name": t["name"],
            "direction": t["direction"],
            "description": t["description"],
            "legs": t["legs"],
            "order": t.get("order", []),
            "anchorModes": ANCHOR_MODES,
            "wingModes": WING_MODES,
        }
        for key, t in TEMPLATES.items()
    ]


def _validate_param(leg: dict, param: dict) -> dict:
    mode = param.get("mode")
    value = param.get("value")
    modes = ANCHOR_MODES if leg["role"] == "anchor" else WING_MODES
    if mode not in modes:
        raise StrategyParamError(f'{leg["label"]}: placement must be one of {", ".join(modes)}')
    if mode == "atm":
        return {"mode": mode, "value": None}
    if value is None or not math.isfinite(value):
        raise StrategyParamError(f'{leg["label"]}: enter a value')
    if mode == "delta" and not 0 < value < 1:
        raise StrategyParamError(f'{leg["label"]}: delta must be between 0 and 1 (e.g. 0.16)')
    if mode == "otm_pct" and not -50 <= value <= 100:
        raise StrategyParamError(f'{leg["label"]}: % OTM must be between -50 and 100')
    if mode == "sigma" and not 0 < value <= 5:
        raise StrategyParamError(f'{leg["label"]}: expected move must be between 0 and 5 σ')
    if mode in ("strike", "width") and value <= 0:
        raise StrategyParamError(f'{leg["label"]}: must be greater than zero')
    if mode == "steps" and (value < 1 or value != int(value)):
        raise StrategyParamError(f'{leg["label"]}: strike steps must be a whole number ≥ 1')
    return {"mode": mode, "value": value}


def _contracts_by_type(chain: dict) -> dict[str, list[dict]]:
    """Flatten the normalized chain into strike-sorted contracts per type,
    priced at mid. A contract with no ask (or a negative bid) is unusable for
    any leg; selling additionally needs a real bid (see _usable)."""
    out = {"PUT": [], "CALL": []}
    for row in chain["chain"]:
        for type_, side in (("PUT", "put"), ("CALL", "call")):
            c = row.get(side)
            if not c:
                continue
            bid, ask = c.get("bid"), c.get("ask")
            if ask is None or ask <= 0 or bid is None or bid < 0 or bid > ask:
                continue
            out[type_].append({
                "symbol": c.get("symbol"),
                "type": type_,
                "strike": float(row["strikePrice"]),
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2,
                "delta": c.get("delta"),
                "iv": c.get("iv"),
            })
    for lst in out.values():
        lst.sort(key=lambda c: c["strike"])
    return out


def _usable(contracts: list[dict], qty: int) -> list[dict]:
    # A zero-bid contract has no buyer: its "mid" is half the ask, a credit
    # nobody would actually pay for it.
    return contracts if qty > 0 else [c for c in contracts if c["bid"] > 0]


def _nearest_index(contracts: list[dict], target: float) -> int:
    return min(range(len(contracts)), key=lambda i: abs(contracts[i]["strike"] - target))


def _by_delta(contracts: list[dict], target: float, type_: str) -> Optional[int]:
    """Index whose |delta| is closest to `target`; ties go further OTM."""
    best = None
    for i, c in enumerate(contracts):
        if c["delta"] is None:
            continue
        key = (abs(abs(c["delta"]) - target), c["strike"] if type_ == "PUT" else -c["strike"])
        if best is None or key < best[0]:
            best = (key, i)
    return best[1] if best else None


def _place_anchor(leg: dict, param: dict, contracts: list[dict], spot: float, iv: Optional[float], dte: int):
    """Index into `contracts` for an anchor leg, or (None, reason)."""
    mode, value = param["mode"], param["value"]
    sign = -1 if leg["type"] == "PUT" else 1  # OTM direction
    if mode == "atm":
        return _nearest_index(contracts, spot), None
    if mode == "strike":
        return _nearest_index(contracts, value), None
    if mode == "otm_pct":
        return _nearest_index(contracts, spot * (1 + sign * value / 100)), None
    if mode == "sigma":
        if not iv:
            return None, "No implied volatility on this chain to compute an expected move"
        move = value * iv * math.sqrt(max(dte, 0.5) / 365)
        return _nearest_index(contracts, spot * math.exp(sign * move)), None
    i = _by_delta(contracts, value, leg["type"])
    if i is None:
        return None, f'{leg["label"]}: no {leg["type"].lower()} deltas on this chain'
    return i, None


def _place_wing(leg: dict, param: dict, contracts: list[dict], anchor_strike: float, spot: float) -> Optional[dict]:
    """The wing contract on the leg's side of `anchor_strike`, or None."""
    side = [c for c in contracts if (c["strike"] > anchor_strike if leg["dir"] > 0 else c["strike"] < anchor_strike)]
    if leg["dir"] < 0:
        side.reverse()  # nearest to the anchor first, in both directions
    if not side:
        return None
    mode, value = param["mode"], param["value"]
    if mode == "steps":
        n = int(value)
        return side[n - 1] if n <= len(side) else None
    if mode == "delta":
        i = _by_delta(side, value, leg["type"])
        return side[i] if i is not None else None
    if mode == "otm_pct":
        # Moneyness is absolute (from spot), not relative to the anchor; a
        # target on the wrong side of the anchor lands on the nearest strike
        # past it, since `side` only holds strikes beyond the anchor.
        target = spot * (1 + (-1 if leg["type"] == "PUT" else 1) * value / 100)
        return side[_nearest_index(side, target)]
    target = anchor_strike + leg["dir"] * value
    return side[_nearest_index(side, target)]


def _candidate(template: dict, placed: dict[str, dict], spot: float, iv: Optional[float], dte: int) -> Optional[dict]:
    legs = [
        {**placed[spec["key"]], "key": spec["key"], "label": spec["label"], "qty": spec["qty"],
         "price": placed[spec["key"]]["mid"]}
        for spec in template["legs"]
    ]
    for a, b in template.get("order", []):
        if not placed[a]["strike"] < placed[b]["strike"]:
            return None
    credit = net_premium(legs)
    if template["direction"] == "credit" and credit <= 0:
        return None
    if template["direction"] == "debit" and credit >= 0:
        return None
    covers = template.get("creditCoversWing")
    if covers and credit < abs(placed[covers[1]]["strike"] - placed[covers[0]]["strike"]):
        return None

    profile = payoff_profile(legs, credit)
    max_profit, max_loss = profile["maxProfit"], profile["maxLoss"]
    pop = probability_of_profit(legs, credit, spot, iv, dte)
    risk = -max_loss if max_loss is not None and max_loss < 0 else None
    ret = None
    if risk and max_profit is not None:
        ret = max_profit / risk
    deltas = [leg["delta"] for leg in legs]
    return {
        "legs": [
            {
                **{k: leg[k] for k in ("key", "label", "symbol", "type", "strike", "qty", "bid", "ask", "mid", "delta", "iv")},
                # Percent out of the money (negative = in the money), same
                # convention as the Screener's moneyness.
                "otmPct": otm_pct(leg["strike"], spot, leg["type"]),
            }
            for leg in legs
        ],
        # Per share, for one unit of the position. Positive = net credit.
        "netPremium": credit,
        # The same at the natural price (sell at the bid, buy at the ask) —
        # what an order filled immediately would get; the copilot's
        # net-credit rule is checked against this, not mid.
        "naturalPremium": sum(-leg["qty"] * (leg["bid"] if leg["qty"] < 0 else leg["ask"]) for leg in legs),
        "maxProfit": max_profit,
        "maxLoss": max_loss,
        "breakevens": profile["breakevens"],
        "pop": pop,
        # Max profit / max risk — for a credit trade the return on the capital
        # at risk, for a debit trade its reward-to-risk ratio. None when
        # either side is unbounded.
        "returnOnRisk": ret,
        "annualizedReturn": ret * 365 / max(dte, 1) if ret is not None and template["direction"] == "credit" else None,
        "pnlAtSpot": payoff(legs, credit, spot),
        "netDelta": sum(leg["qty"] * leg["delta"] for leg in legs) if all(d is not None for d in deltas) else None,
    }


def resolve_params(template_id: str, params: dict, target: Optional[float] = None) -> tuple[dict, dict]:
    """(template, {leg key: validated {"mode", "value"}}) — legs left out of
    `params` get the template default. Raises StrategyParamError, so callers
    can validate before fetching any chain."""
    template = TEMPLATES.get(template_id)
    if template is None:
        raise StrategyParamError(f"Unknown strategy: {template_id}")
    if target is not None and target < 0:
        raise StrategyParamError("Target must be zero or more")
    resolved = {}
    for spec in template["legs"]:
        if spec["role"] == "same":
            continue
        resolved[spec["key"]] = _validate_param(spec, params.get(spec["key"]) or spec["default"])
    return template, resolved


def _rank_key(template: dict):
    """Sort key across candidates — possibly from different expirations:
    closest to the requested placement first, then (credit) the best
    annualized return, which is what makes a 20-DTE and a 45-DTE credit
    comparable, then the better premium (more credit / less debit)."""
    is_credit = template["direction"] == "credit"

    def key(c: dict):
        ann = c.get("annualizedReturn") if is_credit else None
        return (c["distance"], -(ann if ann is not None else -math.inf), -c["netPremium"])

    return key


def combine(template_id: str, results: list[dict]) -> dict:
    """Merge build() results for several expirations of the same strategy
    and parameters into one {"best", "alternatives", "reasons", "params"}.
    The best per expiration compete via _rank_key; alternatives are the
    other expirations' bests, then the winner's own runners-up."""
    template = TEMPLATES[template_id]
    key = _rank_key(template)
    winners = sorted((r for r in results if r["best"]), key=lambda r: key(r["best"]))
    if not winners:
        reasons = []
        for r in results:
            for why in r["reasons"]:
                if why not in reasons:
                    reasons.append(why)
        return {"best": None, "alternatives": [], "reasons": reasons, "params": results[0]["params"] if results else {}}
    top = winners[0]
    alternatives = [r["best"] for r in winners[1:]] + top["alternatives"]
    reasons = []
    missing = len(results) - len(winners)
    if missing:
        reasons.append(f"{missing} of {len(results)} expirations had no qualifying combination")
    return {
        "best": top["best"],
        "alternatives": alternatives[:MAX_RANGE_ALTERNATIVES],
        "reasons": reasons,
        "params": top["params"],
    }


def build(template_id: str, params: dict, chain: dict, target: Optional[float] = None) -> dict:
    """Solve `template_id` against one expiration's normalized `chain`
    (OptionChainProvider.get_option_chain shape).

    `params`: {leg key: {"mode", "value"}} — missing legs use the template
    default. `target`: optional per-share minimum net credit (credit
    templates) or maximum net debit (debit templates).

    Returns {"best", "alternatives", "reasons", "params"} — best is None
    (with reasons saying why) when no combination qualifies.
    """
    template, resolved = resolve_params(template_id, params, target)

    spot, iv, dte = chain["spot"], chain.get("iv"), chain.get("dte") or 0
    by_type = _contracts_by_type(chain)
    pools = {spec["key"]: _usable(by_type[spec["type"]], spec["qty"]) for spec in template["legs"]}
    reasons: list[str] = []

    anchors = [s for s in template["legs"] if s["role"] == "anchor"]
    start = {}
    for spec in anchors:
        pool = pools[spec["key"]]
        if not pool:
            reasons.append(f'{spec["label"]}: no {spec["type"].lower()}s with a usable quote on this chain')
            continue
        i, why = _place_anchor(spec, resolved[spec["key"]], pool, spot, iv, dte)
        if i is None:
            reasons.append(why)
        else:
            start[spec["key"]] = i
    if reasons:
        return {"best": None, "alternatives": [], "reasons": reasons, "params": resolved}

    def resolve(offsets: tuple[int, ...]) -> Optional[dict[str, dict]]:
        placed = {}
        for spec, off in zip(anchors, offsets):
            j = start[spec["key"]] + off
            pool = pools[spec["key"]]
            if not 0 <= j < len(pool):
                return None
            placed[spec["key"]] = pool[j]
        for spec in template["legs"]:
            if spec["role"] == "same":
                strike = placed[spec["of"]]["strike"]
                match = next((c for c in pools[spec["key"]] if c["strike"] == strike), None)
                if match is None:
                    return None
                placed[spec["key"]] = match
        for spec in template["legs"]:
            if spec["role"] == "wing":
                wing = _place_wing(spec, resolved[spec["key"]], pools[spec["key"]], placed[spec["of"]]["strike"], spot)
                if wing is None:
                    return None
                placed[spec["key"]] = wing
        return placed

    grid = [()]
    for _ in anchors:
        grid = [g + (o,) for g in grid for o in range(-SEARCH_STEPS, SEARCH_STEPS + 1)]

    candidates, seen = [], set()
    for offsets in grid:
        placed = resolve(offsets)
        if placed is None:
            continue
        ident = tuple(placed[s["key"]]["symbol"] for s in template["legs"])
        if ident in seen:
            continue
        seen.add(ident)
        cand = _candidate(template, placed, spot, iv, dte)
        if cand is None:
            continue
        cand["distance"] = sum(abs(o) for o in offsets)
        # Each candidate carries its own expiration, since a range build
        # mixes candidates from several.
        cand["expirationDate"] = chain.get("expirationDate")
        cand["dte"] = dte
        cand["iv"] = iv
        candidates.append(cand)

    is_credit = template["direction"] == "credit"
    if not candidates:
        word = "net credit" if is_credit else "net debit"
        reasons.append(f"No combination near these parameters opens for a {word} at mid prices"
                       + (" with total credit covering the call spread" if template.get("creditCoversWing") else ""))
        return {"best": None, "alternatives": [], "reasons": reasons, "params": resolved}

    if target is not None:
        meeting = [c for c in candidates
                   if (c["netPremium"] >= target if is_credit else -c["netPremium"] <= target)]
        if not meeting:
            closest = max(candidates, key=lambda c: c["netPremium"])
            got = closest["netPremium"] if is_credit else -closest["netPremium"]
            reasons.append(
                f'Best {"credit" if is_credit else "debit"} within {SEARCH_STEPS} strikes of these parameters is '
                f'${got:.2f} — {"below" if is_credit else "above"} the ${target:.2f} target'
            )
            return {"best": None, "alternatives": [], "reasons": reasons, "params": resolved}
        candidates = meeting

    # Same ordering a range build uses across expirations (see _rank_key);
    # within one expiration the return tiebreak mostly follows the premium.
    candidates.sort(key=_rank_key(template))
    return {
        "best": candidates[0],
        "alternatives": candidates[1 : 1 + MAX_ALTERNATIVES],
        "reasons": reasons,
        "params": resolved,
    }
