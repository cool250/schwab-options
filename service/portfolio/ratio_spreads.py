"""Grouping legs that together form a ratio spread (buy 1 / sell 2+ at
another strike, opened together) into one record — for closed trades
(group_ratio_spreads) and open positions (group_open_ratio_spreads). Each
falls back to the ungrouped legs rather than risk misstating a number."""

import logging
import math
from collections import defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)


def group_ratio_spreads(trades: List[Dict]) -> List[Dict]:
    """Merge matched-trade legs that together form a ratio spread (e.g.
    buy 1 higher/lower strike, sell 2+ lower/higher strike, same
    underlying/expiration/type, opened the same day) into a single
    grouped record, so a caller sees "one ratio-spread position" instead
    of loose legs it has to reassemble itself.

    Input/output shape: takes the flat list get_option_transactions()
    returns; returns a list of the same shape, except any legs
    identified as one ratio spread are replaced by a single record with
    `"strategy": "RATIO_SPREAD"` as the grouping marker — `"type"` keeps
    its normal meaning (CLOSED/EXPIRED/ASSIGNED/EXERCISED, taken from whichever
    leg closed last), since callers like the UI's Status column read it
    directly and it must mean the same thing on every row. The record
    also carries a `"legs"` list of the original member records, and
    `total_amount`/`close_date` rolled up across the group. `open_price`
    ("Cost basis" in the UI) and `close_price` ("Closing Price") are each
    the short side's quantity-weighted price minus the long side's —
    same net convention as group_open_ratio_spreads' net_trade_price —
    rather than left null, which is what the UI showed before for every
    grouped row. Everything that isn't part of a qualifying group passes
    through unchanged — this never invents a grouping it isn't confident
    about.

    Grouping key: (underlying_symbol, option_type, date) — `date` is
    each leg's *open* date (per OptionTransaction), on the assumption a
    ratio spread is entered as one combo order, so its legs share an
    open date even if they're later closed at different times. A group
    only qualifies if it has legs on exactly two distinct strikes, one
    side net long (BTO) and the other net short (STO) at a *different*
    strike, and the short:long quantity ratio is a whole number >= 2 —
    anything messier (more than two strikes, no clean whole-number
    ratio, or only one side present) is left ungrouped rather than
    guessed at.
    """
    by_key: Dict[tuple, List[Dict]] = defaultdict(list)
    passthrough: List[Dict] = []
    for trade in trades:
        # Still-open ("TRADE") legs are deliberately excluded: grouping
        # would relabel their type away from "TRADE", which is what
        # callers use to know a leg's total_amount is just entry credit,
        # not a realized gain — grouping only ever covers closed/settled
        # legs, where total_amount is a real, summable P&L.
        if trade.get("type") not in ("CLOSED", "EXPIRED", "ASSIGNED", "EXERCISED"):
            passthrough.append(trade)
            continue
        # expirationDate is part of the key, not just underlying/type/date:
        # a ratio spread's legs share one expiration by definition, and
        # without this, two unrelated ratio spreads opened the same day
        # on different expirations (that happen to share a strike, e.g.
        # both shorting the same round-number strike) get lumped into one
        # candidate group, see more than two distinct strikes overall,
        # and silently fail to group at all.
        key = (
            trade.get("underlying_symbol"),
            trade.get("option_type"),
            trade.get("date"),
            trade.get("expirationDate"),
        )
        by_key[key].append(trade)

    grouped: List[Dict] = []
    for (underlying_symbol, option_type, open_date, expiration_date), legs in by_key.items():
        if len(legs) < 2:
            passthrough.extend(legs)
            continue

        by_strike: Dict[float, List[Dict]] = defaultdict(list)
        for leg in legs:
            by_strike[leg.get("strike_price")].append(leg)

        if len(by_strike) != 2:
            passthrough.extend(legs)
            continue

        (strike_a, legs_a), (strike_b, legs_b) = by_strike.items()
        side_a = legs_a[0].get("open_type", "")
        side_b = legs_b[0].get("open_type", "")
        if not all(leg.get("open_type") == side_a for leg in legs_a) or not all(
            leg.get("open_type") == side_b for leg in legs_b
        ):
            # Mixed open_type within one strike — not a clean ratio spread.
            passthrough.extend(legs)
            continue

        if side_a.startswith("B") and side_b.startswith("S"):
            long_strike, long_legs, short_strike, short_legs = strike_a, legs_a, strike_b, legs_b
        elif side_b.startswith("B") and side_a.startswith("S"):
            long_strike, long_legs, short_strike, short_legs = strike_b, legs_b, strike_a, legs_a
        else:
            passthrough.extend(legs)
            continue

        long_qty = sum(leg.get("amount", 0) for leg in long_legs)
        short_qty = sum(leg.get("amount", 0) for leg in short_legs)
        if long_qty <= 0 or short_qty <= 0 or short_qty % long_qty != 0:
            passthrough.extend(legs)
            continue
        ratio = short_qty / long_qty
        if ratio < 2:
            passthrough.extend(legs)
            continue

        def _fmt_strike(s: float) -> str:
            return f"{s:g}"

        def _weighted_price(field: str, side_legs: List[Dict]) -> float:
            # Quantity-weighted average of one side's per-contract price —
            # a side can be more than one same-strike closing lot if the
            # position was trimmed/closed in pieces.
            qty = sum(leg.get("amount", 0) for leg in side_legs)
            if qty == 0:
                return 0.0
            return sum((leg.get(field) or 0) * leg.get("amount", 0) for leg in side_legs) / qty

        cp = "C" if option_type == "CALL" else "P"
        ratio_label = f"{int(long_qty)}:{int(short_qty)}"

        # Net cost basis / closing price for the group — same convention
        # as group_open_ratio_spreads' net_trade_price: short side minus
        # long side, weighted by each side's own quantity, not divided
        # down to a single contract (there's no single "quantity" to
        # divide by once the two sides differ, same reason the group's
        # own "quantity" column shows a ratio like "1:2" rather than a
        # plain number). Without this the UI's Cost Basis/Closing Price
        # columns were blank for every grouped ratio-spread row.
        net_open_price = (short_qty * _weighted_price("open_price", short_legs)
                           - long_qty * _weighted_price("open_price", long_legs))
        net_close_price = (short_qty * _weighted_price("close_price", short_legs)
                            - long_qty * _weighted_price("close_price", long_legs))

        # Real status (CLOSED/EXPIRED/ASSIGNED/EXERCISED), not a grouping marker —
        # the UI's Status column reads `type` directly, so it must keep
        # meaning what it means on every other row. Whichever leg closed
        # last determines it, matching how close_date itself is picked.
        last_leg = max(legs, key=lambda leg: leg.get("close_date", ""))

        grouped.append({
            "type": last_leg.get("type"),
            "strategy": "RATIO_SPREAD",
            "underlying_symbol": underlying_symbol,
            "option_type": option_type,
            "expirationDate": expiration_date,
            "date": open_date,
            "close_date": max(leg.get("close_date", "") for leg in legs),
            "ratio": ratio_label,
            "long_leg": {"strike_price": long_strike, "amount": long_qty},
            "short_leg": {"strike_price": short_strike, "amount": short_qty},
            "total_amount": sum(leg.get("total_amount", 0) for leg in legs),
            "legs": legs,
            # Display-friendly fields so this record renders directly in
            # the same flat-leg table the UI already has, with no
            # special-cased columns for a grouped row.
            "symbol": f"{underlying_symbol} {ratio_label} Ratio "
            f"(+{_fmt_strike(long_strike)}{cp}/-{_fmt_strike(short_strike)}{cp})",
            "open_type": "RATIO SPREAD",
            "amount": ratio_label,
            "open_price": net_open_price,
            "close_price": net_close_price,
        })

    result = sorted(grouped + passthrough, key=lambda t: t.get("close_date", ""))

    # Grouping must be purely organizational — every input leg lands in
    # exactly one output record (standalone or folded into a group's
    # summed total_amount), so the grand total can never legitimately
    # change. Guard it rather than assume it: a future edit to the
    # grouping logic that double-counts or drops a leg would otherwise
    # silently misstate realized P&L.
    input_total = sum(t.get("total_amount", 0) or 0 for t in trades)
    output_total = sum(t.get("total_amount", 0) or 0 for t in result)
    if not math.isclose(input_total, output_total, abs_tol=0.01):
        logger.error(
            "group_ratio_spreads changed the total realized P&L: input=%.2f output=%.2f "
            "(input legs=%d, output records=%d) — grouping bug, falling back to ungrouped.",
            input_total, output_total, len(trades), len(result),
        )
        return trades

    return result


def group_open_ratio_spreads(legs: List[Dict]) -> List[Dict]:
    """Same idea as group_ratio_spreads, but for currently-**open**
    futures-option legs (as returned by get_open_futures_options()) —
    used to display open positions, not closed/realized trade history.

    The key difference from group_ratio_spreads: an open leg's `amount`
    is signed (positive = long/BTO, negative = short/STO), not the
    always-positive magnitude a matched/closed trade carries, so
    quantities here are summed via abs() instead of taken as-is. There's
    no total_amount/realized-P&L concept for an open position, so unlike
    group_ratio_spreads this doesn't need to preserve a `type` field's
    meaning — it just needs to preserve total open contract quantity.

    Same grouping key and qualification rules as group_ratio_spreads
    (two distinct strikes, one side net long, the other net short at a
    whole-number ratio >= 2, all on the same underlying/type/expiration,
    opened the same day) — anything that doesn't cleanly fit is left as
    individual ungrouped legs.

    Grouped records don't have a single meaningful strike_price or
    quantity, so callers building a display row from these should check
    for `"strategy": "RATIO_SPREAD"` and handle those two fields
    specially (see PositionService.get_futures_option_position).
    """
    by_key: Dict[tuple, List[Dict]] = defaultdict(list)
    for leg in legs:
        key = (
            leg.get("underlying_symbol"),
            leg.get("option_type"),
            leg.get("date"),
            leg.get("expirationDate"),
        )
        by_key[key].append(leg)

    grouped: List[Dict] = []
    passthrough: List[Dict] = []
    for (underlying_symbol, option_type, open_date, expiration_date), group_legs in by_key.items():
        if len(group_legs) < 2:
            passthrough.extend(group_legs)
            continue

        by_strike: Dict[float, List[Dict]] = defaultdict(list)
        for leg in group_legs:
            by_strike[leg.get("strike_price")].append(leg)

        if len(by_strike) != 2:
            passthrough.extend(group_legs)
            continue

        (strike_a, legs_a), (strike_b, legs_b) = by_strike.items()
        side_a = legs_a[0].get("open_type", "")
        side_b = legs_b[0].get("open_type", "")
        if not all(leg.get("open_type") == side_a for leg in legs_a) or not all(
            leg.get("open_type") == side_b for leg in legs_b
        ):
            passthrough.extend(group_legs)
            continue

        if side_a.startswith("B") and side_b.startswith("S"):
            long_strike, long_legs, short_strike, short_legs = strike_a, legs_a, strike_b, legs_b
        elif side_b.startswith("B") and side_a.startswith("S"):
            long_strike, long_legs, short_strike, short_legs = strike_b, legs_b, strike_a, legs_a
        else:
            passthrough.extend(group_legs)
            continue

        long_qty = sum(abs(leg.get("amount", 0)) for leg in long_legs)
        short_qty = sum(abs(leg.get("amount", 0)) for leg in short_legs)
        if long_qty <= 0 or short_qty <= 0 or short_qty % long_qty != 0:
            passthrough.extend(group_legs)
            continue
        ratio = short_qty / long_qty
        if ratio < 2:
            passthrough.extend(group_legs)
            continue

        def _fmt_strike(s: float) -> str:
            return f"{s:g}"

        def _weighted_price(side_legs: List[Dict]) -> float:
            # Quantity-weighted average entry price for one side, in case
            # it's made up of more than one same-strike opening trade —
            # all such legs share one contract (same strike/expiration/
            # type/underlying), so a single weighted price and symbol
            # represent the whole side correctly.
            qty = sum(abs(leg.get("amount", 0)) for leg in side_legs)
            if qty == 0:
                return 0.0
            return sum(
                leg.get("open_price", leg.get("price", 0)) * abs(leg.get("amount", 0)) for leg in side_legs
            ) / qty

        cp = "C" if option_type == "CALL" else "P"
        ratio_label = f"{int(long_qty)}:{int(short_qty)}"
        long_price = _weighted_price(long_legs)
        short_price = _weighted_price(short_legs)
        # Net entry price for one whole spread (1 long + `ratio` shorts,
        # in the same per-point convention the individual legs' own
        # trade_price already uses) — what was collected from the short
        # side minus what was paid for the long side. Positive = net
        # credit, negative = net debit.
        net_trade_price = (short_qty * short_price) - (long_qty * long_price)

        grouped.append({
            "underlying_symbol": underlying_symbol,
            "option_type": option_type,
            "expirationDate": expiration_date,
            "date": open_date,
            "strategy": "RATIO_SPREAD",
            "ratio": ratio_label,
            "net_trade_price": net_trade_price,
            "long_leg": {
                "strike_price": long_strike,
                "amount": long_qty,
                "trade_price": long_price,
                "symbol": long_legs[0].get("symbol"),
            },
            "short_leg": {
                "strike_price": short_strike,
                "amount": short_qty,
                "trade_price": short_price,
                "symbol": short_legs[0].get("symbol"),
            },
            "symbol": f"{underlying_symbol} {ratio_label} Ratio "
            f"(+{_fmt_strike(long_strike)}{cp}/-{_fmt_strike(short_strike)}{cp})",
            "legs": group_legs,
        })

    result = grouped + passthrough

    # Same consistency guard as group_ratio_spreads, on total open
    # contract quantity instead of total P&L: every input leg's
    # magnitude must land in exactly one output record.
    input_qty = sum(abs(leg.get("amount", 0) or 0) for leg in legs)
    output_qty = sum(
        (t["long_leg"]["amount"] + t["short_leg"]["amount"]) if t.get("strategy") == "RATIO_SPREAD"
        else abs(t.get("amount", 0) or 0)
        for t in result
    )
    if not math.isclose(input_qty, output_qty, abs_tol=0.001):
        logger.error(
            "group_open_ratio_spreads changed total open contract quantity: input=%.2f "
            "output=%.2f (input legs=%d, output records=%d) — grouping bug, falling back "
            "to ungrouped.",
            input_qty, output_qty, len(legs), len(result),
        )
        return legs

    return result
