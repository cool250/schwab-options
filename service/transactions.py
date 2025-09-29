"""
Transaction Service Module

This module provides functionality to fetch, filter, and analyze transaction history,
with a focus on option transactions.
"""

from collections import defaultdict
from datetime import timedelta
from typing import List, Dict, Any
from loguru import logger
from broker import Accounts, MarketData
from utils.utils import get_date_object, get_date_string


class TransactionService:
    """
    Service for retrieving and analyzing transaction history.
    
    This class provides methods to fetch transaction history and process
    option transactions, including matching opening and closing trades.
    """

    # Constants
    COMMISSION_PER_SHARE = 0.65/100  # $0.0065 per share

    def __init__(self):
        """Initialize the TransactionService with broker API clients."""
        self.market_data = MarketData()
        self.accounts_trading = Accounts()

    def get_transaction_history(self, start_date: str, end_date: str) -> List[Any]:
        """
        Fetch the raw transaction history for the account.
        
        Args:
            start_date (str): Start date in YYYY-MM-DD format
            end_date (str): End date in YYYY-MM-DD format
            
        Returns:
            list: Raw transaction records from the broker
        """
        transactions = self.accounts_trading.fetch_transactions(start_date=start_date, end_date=end_date)
        return transactions if transactions else []
    
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
        transactions = self.accounts_trading.fetch_transactions(
            start_date=expanded_date_range["start_date"], 
            end_date=expanded_date_range["end_date"]
        )
        
        if not transactions:
            logger.error("No transactions found for the given date range.")
            return []

        # Extract and process option transactions
        option_transactions = self._populate_options(stock_ticker, contract_type, transactions)
        
        # Filter out assignments close trade for realized gains only 
        # before matching trades to avoid confusion when a few are rolled over
        filtered_transactions = [
            transaction for transaction in option_transactions
            if not (transaction["position_effect"] == "CLOSING" and 
                   self._identify_trade_type(transaction) == "ASSIGNMENT" and
                   realized_gains_only)
        ]

        # Match opening and closing trades
        matched_transactions = self._match_trades(filtered_transactions)
        
        # Filter by date range and calculate totals
        result_transactions = []
        for transaction in matched_transactions:
            # Skip if we only want realized gains and anything is still open
            if realized_gains_only and transaction["type"] not in ["EXPIRATION", "CLOSED"]:
                continue
                
            # Only include transactions that closed within our original date range
            close_date_str = transaction.get("close_date", "")
            if close_date_str:
                close_date = get_date_object(close_date_str)
                if get_date_object(start_date) <= close_date <= get_date_object(end_date):
                    # Calculate total amount including commission
                    transaction["total_amount"] = (
                        (transaction["price"] - self.COMMISSION_PER_SHARE) * 
                        -transaction["amount"] * 100
                    )
                    result_transactions.append(transaction)

        return result_transactions
        
    def _expand_date_range(self, start_date: str, end_date: str, 
                           lookback_days: int = 60, 
                           lookforward_days: int = 10) -> Dict[str, str]:
        """
        Expand a date range by a specified number of days in both directions.
        
        Args:
            start_date (str): Original start date in YYYY-MM-DD format
            end_date (str): Original end date in YYYY-MM-DD format
            lookback_days (int): Number of days to look back
            lookforward_days (int): Number of days to look forward
            
        Returns:
            dict: Expanded date range with keys 'start_date' and 'end_date'
        """
        start_date_obj = get_date_object(start_date)
        end_date_obj = get_date_object(end_date)
        
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
                    
                if getattr(item.instrument, "assetType", None) != "OPTION":
                    continue
                
                # Extract option details
                underlying_symbol = getattr(item.instrument, "underlyingSymbol", None)
                option_type = getattr(item.instrument, "putCall", None)
                
                # Filter for selected option type
                if contract_type != "ALL" and option_type != contract_type:
                    continue

                # Filter for selected stock ticker   
                if stock_ticker and stock_ticker != underlying_symbol:
                    continue
                
                # Get additional option details
                symbol = getattr(item.instrument, "symbol", "")
                price = float(getattr(item, "price", 0))
                strike_price = getattr(item.instrument, "strikePrice", None)
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
                
                # Create the transaction record
                parsed_transactions.append({
                    "date": trade_date_str,
                    "close_date": expiration_date,
                    "underlying_symbol": underlying_symbol,
                    "expirationDate": expiration_date,
                    "strike_price": strike_price,
                    "symbol": symbol,
                    "price": price,
                    "amount": amount,
                    "position_effect": position_effect,
                    "option_type": option_type,
                    "type": type_of_transaction,
                    "description": description
                })
                
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
                # Calculate weighted average price
                weighted_price = sum(t["price"] * t["amount"] for t in trade_group) / total_amount if total_amount != 0 else 0
                
                # Create a combined trade record
                combined_trade = {
                    **trade_group[0],  # Use first trade as template
                    "amount": total_amount,
                    "price": weighted_price
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
                    # Adjust remaining quantities back in the trades
                    if abs(open_trade["amount"]) > abs(matched_amount):
                        open_trade["amount"] -= amount
                        opens.insert(0, open_trade)  # Reinsert with updated amount
                    if abs(close_trade["amount"]) > abs(matched_amount):
                        close_trade["amount"] += amount  # Close trade amount is negative
                        closes.insert(0, close_trade)  # Reinsert with updated amount
                else: 
                    # Take full amount if they match
                    amount = float(open_trade["amount"])

                # Identify the type of closing trade (normal close, expiration, assignment)
                trade_type = self._identify_trade_type(close_trade)
                
                # Calculate P/L (open price - close price)
                price_difference = float(open_trade.get("price", 0)) - float(close_trade.get("price", 0))

                if trade_type == "ASSIGNMENT":
                    price_difference = 0  # Neutralize amount for assignments
                
                # Use the earliest of close date or expiration date
                # This handles transactions that might be recorded after expiration
                close_date = min(
                    close_trade.get("date", open_trade.get("expirationDate")),
                    open_trade.get("expirationDate", close_trade.get("date"))
                )
                
                # Create the matched trade record with detailed P/L information
                matched_trades.append({
                    "date": open_trade.get("date"),
                    "close_date": close_date,
                    "underlying_symbol": open_trade.get("underlying_symbol"),
                    "expirationDate": open_trade.get("expirationDate"),
                    "strike_price": open_trade.get("strike_price"),
                    "symbol": open_trade.get("symbol"),
                    "price": price_difference,  # P/L per contract
                    "open_price": open_trade.get("price"),  # Original entry price
                    "close_price": close_trade.get("price"),  # Exit price
                    "amount": amount,
                    "position_effect": "MATCHED",
                    "option_type": open_trade.get("option_type"),
                    "type": trade_type
                })

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
            str: The identified trade type - "EXPIRATION", "ASSIGNMENT", "CLOSED", or "UNKNOWN"
        """
        # For RECEIVE_AND_DELIVER transaction types, check the description for specific keywords
        if close_trade.get("type") == "RECEIVE_AND_DELIVER":
            description = close_trade.get("description", "")
            
            if "Expiration" in description:
                return "EXPIRATION"
            elif "Assignment" in description:
                return "ASSIGNMENT"
            else:
                return "UNKNOWN"
        
        # If not a special case, it's a normal close
        return "CLOSED"