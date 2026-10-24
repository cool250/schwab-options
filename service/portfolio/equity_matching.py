"""FIFO matching of equity and outright-futures fills into round trips
(oldest open lot closed first). Pure functions with no broker calls —
tested in tests/test_equity_matching.py."""

import logging
from collections import defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)


def combine_equity_lots(trades: List[Dict]) -> List[Dict]:
    """Collapse same-day, same-symbol, same-direction fills into one lot.

    Grouped by the sign of `amount` rather than Schwab's own `positionEffect`
    — for futures delivered by an option assignment, Schwab tags every such
    fill "OPENING" even when it actually flattens an existing position
    (a same-day buy and sell can both say OPENING), so that field can't be
    trusted to tell same-day fills of opposite direction apart.
    """
    grouped = defaultdict(list)
    for trade in trades:
        key = (trade["date"], trade["symbol"], trade["amount"] > 0)
        grouped[key].append(trade)

    combined = []
    for _, group in grouped.items():
        if len(group) == 1:
            combined.append(group[0])
            continue
        total_amount = sum(t["amount"] for t in group)
        total_abs = sum(abs(t["amount"]) for t in group)
        weighted_price = sum(t["price"] * abs(t["amount"]) for t in group) / total_abs if total_abs else 0
        combined.append({
            **group[0],
            "amount": total_amount,
            "price": weighted_price,
            "cost": sum(t["cost"] for t in group),
        })
    return combined


def match_equity_fills(trades: List[Dict]) -> List[Dict]:
    """
    FIFO-match opens and closes per symbol using a running position built
    purely from the chronological sign of each fill's `amount` — NOT from
    Schwab's own `positionEffect` tag, which is unreliable for futures
    delivered by an option assignment (every such fill says "OPENING", even
    the ones that flatten an existing position).

    A fill that opposes the oldest still-open lot's direction closes it
    (in full or in part, oldest lot first); a fill matching the existing
    direction — or arriving with no open lot to oppose — becomes a new open
    lot itself. A fill can do both: partially close the queue, then open a
    new lot in the opposite direction for whatever quantity flips through.

    The exception is a stock fill the broker tagged CLOSING with nothing
    left to close: its open came before the fetched history, so it's
    reported unmatched but never queued — queued, a sale of shares bought
    before the window would become a phantom short that the next buy
    "closes", pairing unrelated trades. (Stock tags are reliable; futures
    tags aren't, see above, so futures keep the plain sign rule.)

    Realized P&L for a matched (or partially matched) quantity is the sum
    of the proportional share of each side's already-multiplier-correct
    `cost` — this sidesteps ever needing to know the actual per-contract
    multiplier here, since Schwab already baked it into `cost` on each fill.
    """
    by_symbol = defaultdict(list)
    for trade in trades:
        by_symbol[trade["symbol"]].append(trade)

    matched = []
    unmatched = []

    for symbol, group in by_symbol.items():
        fills = sorted(group, key=lambda t: t["date"])
        queue = []  # FIFO of still-open lots: {date, qty (signed), cost, price, asset_type}
        orphans = []  # closes whose open predates the history, same shape

        for fill in fills:
            qty = fill["amount"]
            cost = fill["cost"]
            price = fill["price"]
            date = fill["date"]
            asset_type = fill["asset_type"]

            while abs(qty) > 1e-9 and queue and (queue[0]["qty"] > 0) != (qty > 0):
                lot = queue[0]
                matched_qty = min(abs(lot["qty"]), abs(qty))
                lot_frac = matched_qty / abs(lot["qty"])
                fill_frac = matched_qty / abs(qty)

                matched.append({
                    "date": lot["date"],
                    "close_date": date,
                    "symbol": symbol,
                    "asset_type": asset_type,
                    "quantity": matched_qty,
                    "open_price": lot["price"],
                    "close_price": price,
                    "total_amount": lot["cost"] * lot_frac + cost * fill_frac,
                    "status": "CLOSED",
                    "closed": True,
                })

                lot_sign = 1 if lot["qty"] > 0 else -1
                lot["qty"] = lot_sign * (abs(lot["qty"]) - matched_qty)
                lot["cost"] *= (1 - lot_frac)
                if abs(lot["qty"]) < 1e-9:
                    queue.pop(0)

                fill_sign = 1 if qty > 0 else -1
                qty = fill_sign * (abs(qty) - matched_qty)
                cost *= (1 - fill_frac)

            if abs(qty) > 1e-9:
                lot = {"date": date, "qty": qty, "cost": cost, "price": price, "asset_type": asset_type}
                if asset_type == "EQUITY" and fill.get("position_effect") == "CLOSING":
                    orphans.append(lot)
                else:
                    queue.append(lot)

        for lot in orphans + queue:
            unmatched.append({
                "date": lot["date"],
                "close_date": None,
                "symbol": symbol,
                "asset_type": lot["asset_type"],
                # Signed (positive = long, negative = short) — unlike a closed
                # trade's quantity, an open lot's direction isn't otherwise
                # recoverable from this row, and callers reconstructing a live
                # position (see PositionService.get_futures_position) need it.
                "quantity": lot["qty"],
                "open_price": lot["price"],
                "close_price": None,
                "total_amount": lot["cost"],
                "status": "OPEN",
                "closed": False,
            })

    return matched + unmatched
