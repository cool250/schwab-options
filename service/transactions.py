"""
Transaction Service Module

This module provides functionality to fetch, filter, and analyze transaction history,
with a focus on option transactions.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging
from broker.schwab import Client
from broker.schwab.exceptions import BrokerAuthError, BrokerError
from utils.utils import get_date_object, get_date_string
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Create the transaction record
class OptionTransaction(BaseModel):
    date: str
    close_date: str
    underlying_symbol: str
    expirationDate: str
    strike_price: float
    symbol: str
    price: float
    open_price: float = 0.0
    close_price: float = 0.0
    amount: float
    position_effect: Optional[str] = None
    option_type: str
    type: str
    description: Optional[str] = None
    total_amount: Optional[float] = 0.0
    open_type: Optional[str] = None

class TransactionService:
    """
    Service for retrieving and analyzing transaction history.
    
    This class provides methods to fetch transaction history and process
    option transactions, including matching opening and closing trades.
    """


    # Contract multipliers (points per contract) for non-standard underlyings
    _CONTRACT_MULTIPLIER = {
        "ES": 50,
        "NQ": 20,
    }

    @classmethod
    def _get_multiplier(cls, underlying_symbol: str) -> int:
        return cls._CONTRACT_MULTIPLIER.get(underlying_symbol, 100)

    # Futures prefix rules: first letter after stripping '/' → root symbol
    _FUTURES_PREFIX_MAP = {
        "E": "ES",
        "Q": "NQ",
    }

    @staticmethod
    def _format_option_symbol(underlying_symbol: str, expiration_date: str, option_type: str, strike_price: float) -> str:
        """Build a standard OCC-style option symbol, e.g. 'SPY   260828P00758000'.

        Schwab returns futures options as broker-specific symbols (e.g.
        '/QN3N26_P28500:XCME') instead of OCC format, so this reconstructs the
        familiar '<root><YYMMDD><C/P><strike*1000, 8 digits>' layout from the
        parsed contract fields.
        """
        try:
            yymmdd = datetime.strptime(expiration_date, "%Y-%m-%d").strftime("%y%m%d")
        except (ValueError, TypeError):
            return underlying_symbol
        cp = "C" if option_type == "CALL" else "P"
        strike_str = f"{round(strike_price * 1000):08d}"
        return f"{underlying_symbol:<6}{yymmdd}{cp}{strike_str}"

    @classmethod
    def _normalize_futures_symbol(cls, symbol: str) -> str:
        """Return the CME root symbol for a Schwab futures contract symbol.

        Handles two distinct notations that need different parsing:
        - A futures option's underlying, prefixed with '.' and starting with a
          single-letter product code that doesn't spell the root itself
          ('.QN4M26:XCME' → 'NQ', '.E3DM26_P7050:XCME' → 'ES') — looked up via
          _FUTURES_PREFIX_MAP.
        - An outright futures contract's own symbol, prefixed with '/', where
          the root IS spelled out in full before the 1-letter month code +
          2-digit year ('/ESU26:XCME' → 'ES', '/NQU26:XCME' → 'NQ') — taking
          just the first letter here would wrongly reduce 'NQU26' to 'N'.

        Non-futures symbols (no leading '.' or '/') are returned unchanged.
        """
        if not symbol:
            return symbol

        if symbol.startswith("/"):
            base = symbol.split(":")[0][1:]
            return base[:-3] if len(base) > 3 else base

        if symbol.startswith("."):
            base = symbol.split(":")[0][1:]
            first_letter = base[0] if base else ""
            return cls._FUTURES_PREFIX_MAP.get(first_letter, symbol)

        return symbol

    def __init__(self):
        """Initialize the TransactionService with broker API clients."""
        self.client = Client()
    def get_transaction_history(self, start_date: str, end_date: str) -> List[Any]:
        """
        Fetch the raw transaction history for the account.
        
        Args:
            start_date (str): Start date in YYYY-MM-DD format
            end_date (str): End date in YYYY-MM-DD format
            
        Returns:
            list: Raw transaction records from the broker
        """
        try:
            return self.client.fetch_transactions(start_date=start_date, end_date=end_date)
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to fetch transaction history: %s", e)
            return []
    
    def get_option_transactions(self, stock_ticker: str, start_date: str, end_date: str, 
                             contract_type: str = "ALL", realized_gains_only: bool = True) -> List[Dict]:
        """
        Fetch option transactions, match related trades, and calculate realized gains/losses.
        
        Args:
            stock_ticker (str): The ticker symbol to filter by (e.g., "AAPL")
            start_date (str): Start date in YYYY-MM-DD format
            end_date (str): End date in YYYY-MM-DD format
            contract_type (str, optional): Filter by option type - "PUT", "CALL", or "ALL". Defaults to "ALL"
            realized_gains_only (bool, optional): If True, only return closed positions. Defaults to True
            
        Returns:
            list: Processed option transactions with calculated gains/losses
        """
        # Expand date range to ensure we capture all related trades
        # Looking back 60 days to find opening trades and forward 10 days for closing trades
        expanded_date_range = self._expand_date_range(start_date, end_date, 
                                                     lookback_days=30, 
                                                     lookforward_days=5)
        
        # Fetch transactions with expanded date range
        try:
            transactions = self.client.fetch_transactions(
                start_date=expanded_date_range["start_date"],
                end_date=expanded_date_range["end_date"],
            )
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to fetch transactions: %s", e)
            return []

        if not transactions:
            return []

        # Extract and process option transactions
        option_transactions = self._populate_options(stock_ticker, contract_type, transactions)
        
        # Filter out assignments close trade for realized gains only 
        # before matching trades to avoid confusion when a few are rolled over
        filtered_transactions = [
            transaction for transaction in option_transactions
            if not (transaction["position_effect"] == "CLOSING" and 
                   self._identify_trade_type(transaction) == "ASSIGNED" and
                   realized_gains_only)
        ]

        # Match opening and closing trades
        matched_transactions = self._match_trades(filtered_transactions)
        
        # Filter by date range and calculate totals
        result_transactions = []
        for transaction in matched_transactions:
            # Skip if we only want realized gains and anything is still open
            if realized_gains_only and transaction["type"] not in ["EXPIRED", "CLOSED"]:
                continue
                
            # Only include transactions that closed within our original date range
            close_date_str = transaction.get("close_date", "")
            if close_date_str:
                close_date = get_date_object(close_date_str)
                if get_date_object(start_date) <= close_date <= get_date_object(end_date):
                    result_transactions.append(transaction)

        return result_transactions

    def get_equity_transactions(self, stock_ticker: str, start_date: str, end_date: str,
                                 asset_type: str = "ALL", realized_gains_only: bool = False) -> List[Dict]:
        """
        Fetch FIFO-matched buy/sell round-trips for equities and outright futures
        contracts (i.e. the underlying instrument itself, not options on it).

        Unlike options, there's no strike/expiration to key a contract on, so
        opens and closes are matched by symbol alone, oldest-open-first — the
        standard FIFO cost-basis convention.

        Args:
            stock_ticker (str): Ticker/futures root to filter by (e.g. "AAPL", "ES"). Blank = all.
            start_date (str): Start date in YYYY-MM-DD format
            end_date (str): End date in YYYY-MM-DD format
            asset_type (str, optional): "EQUITY", "FUTURE", or "ALL". Defaults to "ALL"
            realized_gains_only (bool, optional): If True, only return closed round-trips.

        Returns:
            list: [{"date" (opened), "close_date", "symbol", "asset_type", "quantity",
                     "open_price", "close_price", "total_amount", "status"}, ...]
        """
        # Positions can sit open far longer than a weekly option, so look back
        # further than the options matcher does for the opening lot.
        expanded = self._expand_date_range(start_date, end_date, lookback_days=180, lookforward_days=5)

        try:
            transactions = self.client.fetch_transactions(
                start_date=expanded["start_date"], end_date=expanded["end_date"]
            )
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to fetch transactions: %s", e)
            return []

        if not transactions:
            return []

        raw_trades = self._populate_equity_futures(stock_ticker, asset_type, transactions)
        combined = self._combine_equity_lots(raw_trades)
        matched = self._match_equity_open_close(combined)

        results = []
        for trade in matched:
            if realized_gains_only and not trade["closed"]:
                continue
            close_date_str = trade.get("close_date") or ""
            if close_date_str:
                close_date = get_date_object(close_date_str)
                if not (get_date_object(start_date) <= close_date <= get_date_object(end_date)):
                    continue
            elif realized_gains_only:
                continue
            results.append(trade)

        results.sort(key=lambda r: r.get("close_date") or r["date"])
        return results

    def _populate_equity_futures(self, stock_ticker: str, asset_type: str, transactions: List[Any]) -> List[Dict]:
        stock_ticker = stock_ticker.upper()
        results = []
        for transaction in transactions:
            try:
                transfer_items = getattr(transaction, "transferItems", []) or []
                trade_date = getattr(transaction, "tradeDate", None)
                trade_date_str = get_date_string(trade_date) if trade_date else ""

                for item in transfer_items:
                    instrument = getattr(item, "instrument", None)
                    if instrument is None:
                        continue

                    asset = getattr(instrument, "assetType", None)
                    if asset not in ("EQUITY", "FUTURE"):
                        continue
                    if asset_type != "ALL" and asset != asset_type:
                        continue

                    symbol = getattr(instrument, "symbol", "") or ""
                    if stock_ticker and stock_ticker != self._normalize_futures_symbol(symbol):
                        continue

                    amount = float(getattr(item, "amount", 0) or 0)
                    if amount == 0:
                        continue

                    results.append({
                        "date": trade_date_str,
                        "symbol": symbol,
                        "asset_type": asset,
                        "amount": amount,
                        "price": float(getattr(item, "price", 0) or 0),
                        # Schwab's own `cost` already nets in the contract multiplier
                        # (e.g. $50/point for ES) and is credit-positive / debit-negative.
                        "cost": float(getattr(item, "cost", 0) or 0),
                    })
            except Exception as e:
                logger.error(f"Error processing equity/future transaction: {e}")
                continue

        return results

    def _combine_equity_lots(self, trades: List[Dict]) -> List[Dict]:
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

    def _match_equity_open_close(self, trades: List[Dict]) -> List[Dict]:
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
                    queue.append({"date": date, "qty": qty, "cost": cost, "price": price, "asset_type": asset_type})

            for lot in queue:
                unmatched.append({
                    "date": lot["date"],
                    "close_date": None,
                    "symbol": symbol,
                    "asset_type": lot["asset_type"],
                    "quantity": abs(lot["qty"]),
                    "open_price": lot["price"],
                    "close_price": None,
                    "total_amount": lot["cost"],
                    "status": "OPEN",
                    "closed": False,
                })

        return matched + unmatched

    def _expand_date_range(self, start_date: str, end_date: str,
                           lookback_days: int = 60,
                           lookforward_days: int = 10,
                           max_span_days: int = 364) -> Dict[str, str]:
        """
        Expand a date range by a specified number of days in both directions.

        Schwab's transaction API rejects any request spanning more than a year,
        so the requested padding is shrunk (lookback first, since finding the
        opening trade matters more than a few extra days of lookforward) to keep
        the expanded span within `max_span_days` when the caller's own range is
        already large.

        Args:
            start_date (str): Original start date in YYYY-MM-DD format
            end_date (str): Original end date in YYYY-MM-DD format
            lookback_days (int): Number of days to look back
            lookforward_days (int): Number of days to look forward
            max_span_days (int): Hard cap on the total expanded span

        Returns:
            dict: Expanded date range with keys 'start_date' and 'end_date'
        """
        start_date_obj = get_date_object(start_date)
        end_date_obj = get_date_object(end_date)

        user_span_days = (end_date_obj - start_date_obj).days
        available_padding = max(max_span_days - user_span_days, 0)
        lookforward_days = min(lookforward_days, available_padding)
        lookback_days = min(lookback_days, max(available_padding - lookforward_days, 0))

        expanded_start_date = (start_date_obj - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        expanded_end_date = (end_date_obj + timedelta(days=lookforward_days)).strftime('%Y-%m-%d')

        return {
            "start_date": expanded_start_date,
            "end_date": expanded_end_date
        }

    def _populate_options(self, stock_ticker: str, contract_type: str, transactions: List[Any]) -> List[Dict]:
        """
        Extract option transactions from the raw transaction data.
        
        Args:
            stock_ticker (str): The ticker symbol to filter by
            contract_type (str): Filter by option type - "PUT", "CALL", or "ALL"
            transactions (list): Raw transaction records
            
        Returns:
            list: Extracted and parsed option transactions
        """
        parsed_transactions = []
        # Safely process each transaction
        for transaction in transactions:
            try:
                # Safely extract transaction properties
                transfer_items = getattr(transaction, "transferItems", [])
                if transfer_items is None:
                    continue
                type_of_transaction = getattr(transaction, "type", "UNKNOWN")
                description = getattr(transaction, "description", "Trade")
                trade_date = getattr(transaction, "tradeDate", None)
                # Process each transfer item (line item) in the transaction
                for item in transfer_items:
                    # Skip if not an option instrument
                    if not hasattr(item, "instrument") or item.instrument is None:
                        continue
                        
                    if getattr(item.instrument, "assetType") != "OPTION":
                        continue
                    
                    # Extract option details
                    underlying_symbol = self._normalize_futures_symbol(
                        getattr(item.instrument, "underlyingSymbol")
                    )
                    option_type = getattr(item.instrument, "putCall")
                    
                    # Filter for selected option type
                    if contract_type != "ALL" and option_type != contract_type:
                        continue

                    # Filter for selected stock ticker   
                    if stock_ticker and stock_ticker != underlying_symbol:
                        continue
                    
                    # Get additional option details
                    symbol = getattr(item.instrument, "symbol", "") or ""
                    price = float(getattr(item, "price", 0))
                    strike_price = getattr(item.instrument, "strikePrice")
                    amount = float(getattr(item, "amount", 0))
                    position_effect = getattr(item, "positionEffect", None)

                    # Safely handle date conversion
                    try:
                        expiration_date_obj = getattr(item.instrument, "expirationDate", None)
                        expiration_date = get_date_string(expiration_date_obj) if expiration_date_obj else ""

                        trade_date_str = ""
                        if trade_date:
                            trade_date_str = get_date_string(trade_date)
                    except Exception as e:
                        logger.error(f"Error processing dates: {e}")
                        expiration_date = ""
                        trade_date_str = ""

                    # Futures options come back as broker-specific symbols (e.g.
                    # '/QN3N26_P28500:XCME') instead of Schwab's usual OCC-style
                    # equity option symbols — reformat to match. Schwab also
                    # sometimes omits the symbol entirely (returns null) on
                    # legitimate legs (seen on TRADE and RECEIVE_AND_DELIVER
                    # records), so synthesize one from the parsed fields rather
                    # than dropping the transaction.
                    if (not symbol or symbol.startswith("/")) and expiration_date:
                        symbol = self._format_option_symbol(
                            underlying_symbol, expiration_date, option_type, strike_price
                        )

                    # Create the option transaction record
                    open_type = None
                    if position_effect == "OPENING":
                        open_type = "BTO" if amount > 0 else "STO"

                    parsed_transactions.append(OptionTransaction(
                        date=trade_date_str,
                        close_date=expiration_date,
                        underlying_symbol=underlying_symbol,
                        expirationDate=expiration_date,
                        strike_price=strike_price,
                        symbol=symbol,
                        price=price,
                        amount=amount,
                        position_effect=position_effect,
                        option_type=option_type,
                        type=type_of_transaction,
                        description=description,
                        total_amount=price * -amount * self._get_multiplier(underlying_symbol),
                        open_price=price if position_effect == "OPENING" else 0.0,
                        close_price=price if position_effect == "CLOSING" else 0.0,
                        open_type=open_type,
                    ).model_dump())
            except Exception as e:
                logger.error(f"Error processing transaction: {e}")
                continue

        return parsed_transactions

    def _match_trades(self, trades: List[Dict]) -> List[Dict]:
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
        combine_lot_trades = self._combine_common_lots(trades)

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
        combined_trades = self._match_open_close(open_close_trades)
            
        return combined_trades
    
    def _combine_common_lots(self, trades: List[Dict]) -> List[Dict]:
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

    def _match_open_close(self, contract_trades: Dict) -> List[Dict]:
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
                    multiplier = self._get_multiplier(open_trade["underlying_symbol"])
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
                trade_type = self._identify_trade_type(close_trade)
                
                # Calculate P/L (open price - close price)
                price_difference = float(open_trade.get("price", 0)) - float(close_trade.get("price", 0))

                if trade_type == "ASSIGNED":
                    price_difference = 0  # Neutralize amount for assignments
                
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
                    total_amount=price_difference * -amount * self._get_multiplier(open_trade.get("underlying_symbol", "")),
                    open_type=open_trade.get("open_type"),
                ).model_dump())

            # Add any remaining unmatched trades to the unmatched list
            if closes: # Update the type for any remaining unmatched close trades EXPIRED or ASSIGNMENT or CLOSED
                for close_trade in closes:
                    close_trade["type"] = self._identify_trade_type(close_trade)
            unmatched_trades.extend(opens + closes)

        # Combine matched and unmatched trades, sort by close date, and clean up
        all_trades = matched_trades + unmatched_trades
        all_trades.sort(key=lambda x: x.get("close_date", ""))
        
        # Remove description field which is no longer needed
        for trade in all_trades:
            trade.pop("description", None)
            trade.pop("position_effect", None)  # Remove position_effect as it's now implicit
        
        return all_trades

    def _identify_trade_type(self, close_trade: Dict) -> str:
        """
        Identify the type of trade (expiration, assignment, or regular close).
        
        Args:
            close_trade (dict): The trade record to analyze
            
        Returns:
            str: The identified trade type - "EXPIRATION", "ASSIGNMENT", or "CLOSED"
        """
        # For RECEIVE_AND_DELIVER transaction types, check the description for specific keywords
        if close_trade.get("type") == "RECEIVE_AND_DELIVER":
            description = close_trade.get("description", "")

            if "Expiration" in description:
                return "EXPIRED"
            elif "Assignment" in description:
                return "ASSIGNED"
            else:
                logger.warning(
                    "Unrecognized RECEIVE_AND_DELIVER description for %s: %r — treating as CLOSED",
                    close_trade.get("symbol"), description
                )
                return "CLOSED"
        
        # If not a special case, it's a normal close
        return "CLOSED"