"""Matching option legs into trades: per contract, opens are paired with
closes oldest-first, giving realized P&L and how each trade ended (closed,
expired, assigned, exercised). Pure functions with no broker calls —
tested directly in tests/test_option_matching.py."""

import logging
from collections import defaultdict
from typing import Dict, List

from service.portfolio.providers.base import OptionTransaction
from service.shared.contracts import get_contract_multiplier

logger = logging.getLogger(__name__)


def identify_trade_type(close_trade: Dict) -> str:
    """
    Identify the type of trade (expiration, assignment, futures-option
    exercise, or regular close),
    from the close_event the provider already computed at parse time (see
    SchwabTransactionProvider._identify_close_event) — the old raw Schwab
    RECEIVE_AND_DELIVER-type + English-description sniffing now lives
    there, broker-specific, instead of here.

    Args:
        close_trade (dict): The trade record to analyze

    Returns:
        str: The identified trade type - "EXPIRED", "ASSIGNED", "EXERCISED" or "CLOSED"
    """
    close_event = close_trade.get("close_event")
    if close_event == "EXPIRATION":
        return "EXPIRED"
    if close_event == "ASSIGNMENT":
        return "ASSIGNED"
    if close_event == "EXERCISE":
        return "EXERCISED"
    return "CLOSED"


def match_option_trades(trades: List[Dict]) -> List[Dict]:
    """
    Match opening and closing option trades by contract identity and date.

    This method performs several steps:
    1. Group trades opened on the same day with same attributes
    2. Combine opening and closing trades for the same contract
    3. Match open/close trades and calculate profit/loss for matched trades

    Args:
        trades (list): List of parsed option trade records

    Returns:
        list: Matched trades with profit/loss calculations and unmatched trades
    """
    # STEP 1: Combine trades opened for same lots on the same day with same attributes
    combine_lot_trades = combine_common_lots(trades)

    # STEP 2: Group opening and closing trades for the same option contract
    # Group by option contract key (underlying, strike, expiration, option type)
    open_close_trades = defaultdict(list)
    for trade in combine_lot_trades:
        key = (
            trade["underlying_symbol"], 
            trade["strike_price"], 
            trade["expirationDate"], 
            trade["option_type"]
        )
        open_close_trades[key].append(trade)

    # STEP 3: Process each contract's trades to match opening and closing positions and 
    combined_trades = match_open_close(open_close_trades)

    return combined_trades


def combine_common_lots(trades: List[Dict]) -> List[Dict]:
    # STEP 1A: Group trades opened on same day with same attributes
    # This handles cases where trades were split into multiple transactions
    # Groups them to process together
    position_grouped = defaultdict(list)
    for trade in trades:
        key = (
            trade["date"], 
            trade["underlying_symbol"], 
            trade["strike_price"], 
            trade["expirationDate"], 
            trade["position_effect"], 
            trade["option_type"]
        )
        position_grouped[key].append(trade)

    # STEP 1B: Collapses trades with the same key by summing quantities and averaging prices
    grouped_trades = []
    for key, trade_group in position_grouped.items():
        if len(trade_group) > 1:
            # Multiple trades with the same characteristics - combine them
            total_amount = sum(t["amount"] for t in trade_group)
            # Calculate weighted average price using absolute quantities to handle signed amounts correctly
            total_abs = sum(abs(t["amount"]) for t in trade_group)
            weighted_price = sum(t["price"] * abs(t["amount"]) for t in trade_group) / total_abs if total_abs != 0 else 0

            # Create a combined trade record
            combined_total_amount = sum(t["total_amount"] for t in trade_group)
            position_effect = trade_group[0]["position_effect"]
            combined_trade = {
                **trade_group[0],  # Use first trade as template
                "amount": total_amount,
                "price": weighted_price,
                "total_amount": combined_total_amount,
                "open_price": weighted_price if position_effect == "OPENING" else trade_group[0]["open_price"],
                "close_price": weighted_price if position_effect == "CLOSING" else trade_group[0]["close_price"],
            }
        else:
            # Only one trade with these characteristics
            combined_trade = trade_group[0]

        grouped_trades.append(combined_trade)

    return grouped_trades


def match_open_close(contract_trades: Dict) -> List[Dict]:
    # STEP 3: Process each contract's trades to match opening and closing positions and
    matched_trades = []
    unmatched_trades = []

    for contract_key, trade_group in contract_trades.items():
        # Separate opening and closing trades
        opens = [t for t in trade_group if t["position_effect"] == "OPENING"]
        closes = [t for t in trade_group if t["position_effect"] == "CLOSING"]

        # Sort by date to pair in chronological order
        opens.sort(key=lambda x: x.get("date", ""))
        closes.sort(key=lambda x: x.get("date", ""))

        # Match opens and closes until we run out of one or both
        while opens and closes:
            open_trade = opens.pop(0)
            close_trade = closes.pop(0)

            # Handle cases where quantities don't match exactly
            if open_trade["amount"] != -close_trade["amount"]:
                # Use the minimum of the amounts for matching
                matched_amount = min(abs(open_trade["amount"]), abs(close_trade["amount"]))
                amount = matched_amount if open_trade["amount"] > 0 else -matched_amount # Determine sign based on opening trade
                logger.warning(
                    f"Unmatched trade quantities for {contract_key}: "
                    f"Open qty {open_trade['amount']}, Close qty {close_trade['amount']}"
                )
                # Adjust remaining quantities back in the trades and recalculate total_amount
                multiplier = get_contract_multiplier(open_trade["underlying_symbol"])
                if abs(open_trade["amount"]) > abs(matched_amount):
                    open_trade["amount"] -= amount
                    open_trade["total_amount"] = (
                        open_trade["price"] * -open_trade["amount"] * multiplier
                    )
                    opens.insert(0, open_trade)  # Reinsert with updated amount
                if abs(close_trade["amount"]) > abs(matched_amount):
                    close_trade["amount"] += amount  # Close trade amount is negative
                    close_trade["total_amount"] = (
                        close_trade["price"] * -close_trade["amount"] * multiplier
                    )
                    closes.insert(0, close_trade)  # Reinsert with updated amount
            else: 
                # Take full amount if they match
                amount = float(open_trade["amount"])

            # Identify the type of closing trade (normal close, expiration, assignment)
            trade_type = identify_trade_type(close_trade)

            # Calculate P/L (open price - close price)
            price_difference = float(open_trade.get("price", 0)) - float(close_trade.get("price", 0))

            # ASSIGNED (an equity option) and EXERCISED (a futures option)
            # keep their premium as P&L: the delivered shares / future are
            # booked at the strike, so the premium is the option's whole
            # contribution, and zeroing it would drop it from the total
            # entirely (as thinkorswim's own P&L also counts it).

            # Use the earliest of close date or expiration date
            # This handles transactions that might be recorded after expiration
            close_date = min(
                close_trade.get("date", open_trade.get("expirationDate")),
                open_trade.get("expirationDate", close_trade.get("date"))
            )

            # Create the matched trade record with detailed P/L information
            matched_trades.append(OptionTransaction(
                date=open_trade.get("date"),
                close_date=close_date,
                underlying_symbol=open_trade.get("underlying_symbol"),
                expirationDate=open_trade.get("expirationDate"),
                strike_price=open_trade.get("strike_price"),
                symbol=open_trade.get("symbol"),
                price=price_difference,  # P/L per contract
                open_price=open_trade.get("price"),  # Original entry price
                close_price=close_trade.get("price"),  # Exit price
                amount=abs(amount),
                position_effect="MATCHED",
                option_type=open_trade.get("option_type"),
                type=trade_type,
                total_amount=price_difference * -amount * get_contract_multiplier(open_trade.get("underlying_symbol", "")),
                open_type=open_trade.get("open_type"),
            ).model_dump())

        # Add any remaining unmatched trades to the unmatched list
        if closes: # Update the type for any remaining unmatched close trades EXPIRED or ASSIGNMENT or CLOSED
            for close_trade in closes:
                close_trade["type"] = identify_trade_type(close_trade)
        unmatched_trades.extend(opens + closes)

    # Combine matched and unmatched trades, sort by close date, and clean up
    all_trades = matched_trades + unmatched_trades
    all_trades.sort(key=lambda x: x.get("close_date", ""))

    # Remove fields that are now implicit/internal
    for trade in all_trades:
        trade.pop("position_effect", None)
        trade.pop("close_event", None)

    return all_trades
