"""The options-wheel numbers behind the copilot's get_wheel_snapshot tool
(copilot/tools.py) and its playbook (copilot/skills/options_wheel.md):
notional exposure and leverage, the risk mode they set, how many more calls
each underlying can cover, and the loss budget from the year's realized P&L.

Computed here rather than left to the model, so the mode and the no-naked-
calls check are arithmetic, not judgment. Pure functions over plain rows
(the Portfolio models as dicts) — tested in tests/test_copilot_wheel.py.
"""

from typing import Optional

from service.shared.contracts import get_contract_multiplier

EQUITY_MULTIPLIER = 100


def _root(symbol: str) -> str:
    return symbol.lstrip("/").upper()


def notional_by_underlying(stocks: list[dict], equity_puts: list[dict], futures: list[dict],
                           futures_option_puts: list[dict]) -> dict[str, dict]:
    """Full contract value per underlying, split by kind:
    stock |qty| x price, futures |qty| x price x point value, short puts
    strike x contracts x multiplier. Short calls add nothing — they're
    covered by the shares, futures or long calls already counted (see
    call_coverage) — and long options only risk their premium. A row
    without a price is left out and counted in `unpriced`."""
    by: dict[str, dict] = {}

    def add(underlying: str, kind: str, value: Optional[float]):
        entry = by.setdefault(underlying, {"stock": 0.0, "futures": 0.0, "short_puts": 0.0, "total": 0.0, "unpriced": 0})
        if value is None:
            entry["unpriced"] += 1
            return
        entry[kind] += value
        entry["total"] += value

    for s in stocks:
        price = s.get("current_price")
        add(s["symbol"], "stock", None if price is None else abs(s["quantity"]) * price)
    for f in futures:
        price = f.get("current_price")
        root = _root(f["symbol"])
        add(f"/{root}", "futures", None if price is None else abs(f["quantity"]) * price * get_contract_multiplier(root))
    for p in equity_puts:
        if p["quantity"] < 0:
            add(p["ticker"], "short_puts", p["strike_price"] * -p["quantity"] * EQUITY_MULTIPLIER)
    for p in futures_option_puts:
        root = _root(p["ticker"])
        for strike, qty in _option_legs(p):
            if qty < 0:
                # The point value (/ES 50, /NQ 20), never the equity 100.
                add(f"/{root}", "short_puts", strike * -qty * (p.get("multiplier") or get_contract_multiplier(root)))
    return by


def _option_legs(row: dict) -> list[tuple[float, float]]:
    """(strike, signed contracts) per leg — a grouped ratio-spread row has a
    long and a short leg (unsigned amounts) instead of strike/quantity."""
    if row.get("long_leg") and row.get("short_leg"):
        return [(row["long_leg"]["strike_price"], row["long_leg"]["amount"]),
                (row["short_leg"]["strike_price"], -row["short_leg"]["amount"])]
    return [(row["strike_price"], row["quantity"])]


def call_coverage(stocks: list[dict], equity_calls: list[dict], futures: list[dict],
                  futures_option_calls: list[dict]) -> dict[str, dict]:
    """Per underlying: short calls, what covers them, and how many more
    short calls could be sold without any being naked.

    Cover is whole lots of 100 long shares, long futures (one option per
    future — /ES options on /ES), and long calls — but a long call counts
    only if it expires on or after the latest short call there, so cover
    is never overstated. `naked` > 0 means the account already has
    uncovered short calls."""
    by: dict[str, dict] = {}

    def entry(underlying: str) -> dict:
        return by.setdefault(underlying, {"shares_lots": 0, "long_futures": 0, "long_calls": [], "short_calls": []})

    for s in stocks:
        if s["quantity"] > 0:
            entry(s["symbol"])["shares_lots"] += int(s["quantity"] // EQUITY_MULTIPLIER)
    for f in futures:
        if f["quantity"] > 0:
            entry(f"/{_root(f['symbol'])}")["long_futures"] += f["quantity"]
    for rows, futures_root in ((equity_calls, False), (futures_option_calls, True)):
        for c in rows:
            underlying = f"/{_root(c['ticker'])}" if futures_root else c["ticker"]
            for _strike, qty in _option_legs(c):
                side = "long_calls" if qty > 0 else "short_calls"
                entry(underlying)[side].append((abs(qty), c.get("expiration_date") or ""))

    result = {}
    for underlying, e in by.items():
        short = sum(q for q, _ in e["short_calls"])
        latest_short = max((exp for _, exp in e["short_calls"]), default="")
        long_cover = sum(q for q, exp in e["long_calls"] if exp >= latest_short)
        cover = e["shares_lots"] + e["long_futures"] + long_cover
        result[underlying] = {
            "short_calls": short,
            "covered_by": {"share_lots": e["shares_lots"], "long_futures": e["long_futures"], "long_calls": long_cover},
            "free_cover": max(0, cover - short),
            "naked": max(0, short - cover),
        }
    return result


def ratio_call_floors(futures: list[dict], max_below_entry_pct: int) -> dict[str, dict]:
    """Per futures root held long: the cheapest open lot's trade price and
    the lowest strike a wind-down call ratio's short calls may use —
    max_below_entry_pct below it. Positions without lots fall back to the
    blended trade price."""
    floors = {}
    for f in futures:
        if f["quantity"] <= 0:
            continue
        entries = [lot["trade_price"] for lot in f.get("lots") or [] if lot["quantity"] > 0] or [f["trade_price"]]
        cheapest = min(entries)
        floors[f"/{_root(f['symbol'])}"] = {
            "cheapest_lot_entry": cheapest,
            "lowest_short_strike": round(cheapest * (1 - max_below_entry_pct / 100), 2),
        }
    return floors


def risk_mode(leverage_pct: Optional[float], aggressive_max_pct: int, defensive_min_pct: int) -> Optional[str]:
    if leverage_pct is None:
        return None
    if leverage_pct < aggressive_max_pct:
        return "aggressive"
    return "defensive" if leverage_pct >= defensive_min_pct else "neutral"


def delta_bands(mode: Optional[str], settings: dict) -> dict:
    """The delta range (hundredths, [low, high]) for new short puts and calls
    in `mode` — None for puts in defensive mode, which sells none, and for
    both when the mode is unknown."""
    if mode is None:
        return {"put": None, "call": None}
    return {
        "put": None if mode == "defensive" else settings[f"wheel.{mode}_put_delta_pct"],
        "call": settings[f"wheel.{mode}_call_delta_pct"],
    }


def realized_pl(option_rows: list[dict], equity_rows: list[dict]) -> float:
    """Realized trading P&L the way the Reports page totals it: closed option
    legs (not still-open "TRADE" rows) plus closed stock / futures round
    trips (not open lots, nor the opening fills of short positions)."""
    options = sum(r.get("total_amount") or 0 for r in option_rows if r.get("close_date") and r.get("type") != "TRADE")
    equity = sum(
        r.get("total_amount") or 0
        for r in equity_rows
        if r.get("close_price") is not None and (r.get("quantity") or 0) >= 0
    )
    return options + equity


def snapshot(*, net_liquidity: Optional[float], notional: dict[str, dict], coverage: dict[str, dict],
             ytd_realized: float, mtd_realized: float, settings: dict, futures: Optional[list[dict]] = None) -> dict:
    total = sum(n["total"] for n in notional.values())
    leverage = None if not net_liquidity or net_liquidity <= 0 else round(total / net_liquidity * 100, 1)
    aggressive_max = settings["wheel.aggressive_max_leverage_pct"]
    defensive_min = max(settings["wheel.defensive_min_leverage_pct"], aggressive_max)
    budget_pct = settings["wheel.loss_budget_pct"]
    mode = risk_mode(leverage, aggressive_max, defensive_min)
    return {
        "net_liquidity": net_liquidity,
        "notional_total": round(total, 2),
        "notional_by_underlying": notional,
        "leverage_pct": leverage,
        "mode": mode,
        "mode_bands_pct": {"aggressive_below": aggressive_max, "defensive_from": defensive_min},
        # Delta ranges for new short options in this mode (hundredths).
        "new_trade_delta_pct": delta_bands(mode, settings),
        "call_coverage": coverage,
        # Wind-down call ratios: the lowest short strike per futures root.
        "ratio_call_floors": {
            "max_below_entry_pct": settings["wheel.ratio_call_max_below_entry_pct"],
            "by_root": ratio_call_floors(futures or [], settings["wheel.ratio_call_max_below_entry_pct"]),
        },
        "realized_pl": {"month_to_date": round(mtd_realized, 2), "year_to_date": round(ytd_realized, 2)},
        "loss_budget": {"pct_of_ytd": budget_pct, "dollars": round(max(0.0, ytd_realized) * budget_pct / 100, 2)},
        # A short option that has kept this percent of its premium is a
        # take-profit candidate — the Home page's rule.
        "take_profit_pct": settings["home.take_profit_pct"],
        # New trades mostly expire within this many days — the Home page's
        # New Income window.
        "max_dte": settings["home.idea_max_dte"],
    }
