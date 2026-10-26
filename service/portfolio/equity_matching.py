"""FIFO matching of equity and outright-futures fills into round trips
(oldest open lot closed first). Pure functions with no broker calls —
tested in tests/test_equity_matching.py."""

import logging
from collections import defaultdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def combine_equity_lots(trades: List[Dict]) -> List[Dict]:
    """Collapse same-day, same-symbol, same-direction fills into one lot.

    Grouped by the sign of `amount` rather than Schwab's own `positionEffect`
    — for futures delivered by an option assignment, Schwab tags every such
    fill "OPENING" even when it actually flattens an existing position
    (a same-day buy and sell can both say OPENING), so that field can't be
    trusted to tell same-day fills of opposite direction apart.

    Stock fills are also kept apart by their tag (reliable for stock): a
    same-day buy that covers a short (CLOSING) and one that opens a long
    (OPENING) are different lots. Merged, the cover became an opening buy
    and every later fill paired with the wrong lot (an account short 1,300
    SPY read as long 400).
    """
    grouped = defaultdict(list)
    for trade in trades:
        effect = trade.get("position_effect") if trade.get("asset_type") == "EQUITY" else None
        key = (trade["date"], trade["symbol"], trade["amount"] > 0, effect)
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

    Stock fills follow their tags instead, which are reliable for stock
    (futures tags aren't, see above, so futures and untagged fills keep the
    plain sign rule): an OPENING fill always starts a new lot, never closing
    one — a short sale opened by an assigned call while long shares are
    still on the books is a new short, not a sale of those shares — and a
    CLOSING fill closes the oldest opposite lots. A CLOSING fill with
    nothing left to close has its open before the fetched history: it's
    reported as a close with an unknown open (date None, total 0, not
    "closed" — no realized P&L can be known) and never queued, since queued
    it would become a phantom lot that the next fill "closes".

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
        # Within a day, opening fills first, so a same-day close (an assigned
        # put's shares sold the day they arrive) has its open to match.
        fills = sorted(group, key=lambda t: (t["date"], 0 if t.get("position_effect") == "OPENING" else 1))
        queue = []  # FIFO of still-open lots: {date, qty (signed), cost, price, asset_type}
        orphans = []  # closes whose open predates the history, same shape

        for fill in fills:
            qty = fill["amount"]
            cost = fill["cost"]
            price = fill["price"]
            date = fill["date"]
            asset_type = fill["asset_type"]

            effect = fill.get("position_effect") if asset_type == "EQUITY" else None
            # The oldest open lot on the other side. (Stock lots can be long
            # and short at once — an OPENING fill never closes — so it isn't
            # always the first in the queue.)
            while effect != "OPENING" and abs(qty) > 1e-9:
                lot = next((l for l in queue if (l["qty"] > 0) != (qty > 0)), None)
                if lot is None:
                    break
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
                    queue.remove(lot)

                fill_sign = 1 if qty > 0 else -1
                qty = fill_sign * (abs(qty) - matched_qty)
                cost *= (1 - fill_frac)

            if abs(qty) > 1e-9:
                lot = {"date": date, "qty": qty, "cost": cost, "price": price, "asset_type": asset_type}
                if effect == "CLOSING":
                    orphans.append(lot)
                else:
                    queue.append(lot)

        for lot in orphans:
            unmatched.append({
                "date": None,
                "close_date": lot["date"],
                "symbol": symbol,
                "asset_type": lot["asset_type"],
                "quantity": abs(lot["qty"]),
                "open_price": None,
                "close_price": lot["price"],
                "total_amount": 0.0,
                "status": "CLOSED",
                "closed": False,
                "open_unknown": True,
            })
        for lot in queue:
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


def cost_of_held_position(fills: List[Dict], held: float) -> Optional[float]:
    """Per-share price of the `held` shares (signed: negative = short) as
    the fills that built them were priced, or None if `fills` doesn't reach
    back far enough to account for all of them.

    Under FIFO, what's still open is the newest fills in the position's
    direction: walking back from the latest, take those fills (only the
    part still needed from the oldest one) until they add up to `held`.
    Fills the other way only ever closed older lots, so they're skipped.
    Working back from today means a history that starts partway through
    the position's life can't mis-pair anything — it just comes up short.
    """
    if abs(held) < 1e-9:
        return None
    need, cost = abs(held), 0.0
    for fill in sorted(fills, key=lambda f: f["date"], reverse=True):
        if (fill["amount"] > 0) != (held > 0) or not fill.get("price"):
            continue
        take = min(abs(fill["amount"]), need)
        cost += take * fill["price"]
        need -= take
        if need < 1e-9:
            return cost / abs(held)
    return None
