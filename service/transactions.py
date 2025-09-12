from collections import defaultdict
from datetime import timedelta
from loguru import logger
from broker.accounts import AccountsTrading
from broker.market_data import MarketData
from model.account_models import SecuritiesAccount
from utils.utils import convert_date_string, get_date_object, get_date_string

def parse_option_symbol(symbol):
    """Parse the option symbol to extract ticker, strike price, and expiration date."""
    try:
        strike_price = float(symbol[13:21]) / 1000
        ticker = symbol[:6].strip()
        expiration_date = f"{symbol[6:8]}-{symbol[8:10]}-{symbol[10:12]}"
        return ticker, strike_price, expiration_date
    except ValueError as e:
        logger.error(f"Error parsing option symbol {symbol}: {e}")
        return None, None, None

class TransactionService:

    def __init__(self):
        self.market_data = MarketData()
        self.accounts_trading = AccountsTrading()

    def get_transaction_history(self, start_date: str, end_date: str):
        """Fetch the transaction history for the account."""
        transactions = self.accounts_trading.fetch_transactions(start_date=start_date, end_date=end_date)
        return transactions
    
    def get_option_transactions(self, start_date: str, end_date: str, stock_ticker: str, contract_type: str = "ALL"):
        """Fetch option transactions and parse their details."""

        # For options, we want to look back 60 days and forward 5 days to ensure we capture all related trades
        # with options expiring within the selected range
        start_date_obj = get_date_object(start_date)  # Ensure start_date is converted to datetime
        modified_start_date = (start_date_obj - timedelta(days=60)).strftime('%Y-%m-%d')

        end_date_obj = get_date_object(end_date)
        modified_end_date = (end_date_obj + timedelta(days=10)).strftime('%Y-%m-%d')

        transactions = self.accounts_trading.fetch_transactions(start_date=modified_start_date, end_date=modified_end_date)
        if not transactions:
            logger.error("No transactions found for the given date range.")
            return []

        parsed_transactions = self._populate_options(stock_ticker, contract_type, transactions)
        matched_transactions = self._match_trades(parsed_transactions)
        
        # Filter by date range
        filtered_transactions = []
        for transaction in matched_transactions:
            if get_date_object(start_date) <= get_date_object(transaction.get("close_date")) <= get_date_object(end_date):
                transaction["total_amount"] = -transaction["price"] * transaction["amount"] * 100
                filtered_transactions.append(transaction)
        return filtered_transactions

    def _populate_options(self, stock_ticker, contract_type, transactions):
        parsed_transactions = []
        for transaction in transactions:
            transfer_items = getattr(transaction, "transferItems", None)
            type_of_transaction = getattr(transaction, "type", "None")
            description = getattr(transaction, "description", "Trade")
      
            for item in transfer_items:
                if item.instrument is not None and getattr(item.instrument, "assetType", None) == "OPTION":
                    underlyingSymbol = getattr(item.instrument, "underlyingSymbol", None)
                    optionType = getattr(item.instrument, "putCall", None)
                    # Filter by stock ticker and contract type if provided
                    if contract_type != "ALL" and optionType != contract_type:
                        continue
                    if stock_ticker and stock_ticker != underlyingSymbol:
                        continue
                    symbol = getattr(item.instrument, "symbol", "")  # Default to empty string if None
                    price = float(getattr(item, "price", 0))
                    strikePrice = getattr(item.instrument, "strikePrice", None)
                    amount = float(item.amount)
                    expiration_date = get_date_string(getattr(item.instrument, "expirationDate", None))
                    parsed_transactions.append({
                        "date": get_date_string(getattr(transaction, "tradeDate", "")) if getattr(transaction, "tradeDate", None) else "",
                        "close_date": expiration_date,
                        "underlying_symbol": underlyingSymbol,
                        "expirationDate": expiration_date,
                        "strike_price": strikePrice,
                        "symbol": symbol,
                        "price": price,
                        "amount": amount,
                        "position_effect": getattr(item, "positionEffect", None),
                        "option_type": optionType,
                        "type": type_of_transaction,
                        "description": description
                    })
        return parsed_transactions

    def _match_trades(self, trades):
        """
        Matches opening and closing option trades by contract identity and date.

        Returns:
            List[dict]: A list where the first elements are matched trades (dicts with open/close info),
                        and the remaining elements are unmatched trades (with the original trade structure).
                        The structure of matched and unmatched trades differs.
        """
        # Group trades by contract identity
        position_grouped = defaultdict(list)
        for trade in trades:
            key = (trade["underlying_symbol"], trade["strike_price"], trade["expirationDate"], trade["position_effect"], trade["option_type"])
            position_grouped[key].append(trade)

        grouped_trades = []
        # Combine trades with the same key by summing quantities and averaging the prices
        for key, trade_group in position_grouped.items():
            if len(trade_group) > 1:
                total_amount = sum(t["amount"] for t in trade_group)
                price = sum(t["price"] * t["amount"] for t in trade_group) / total_amount if total_amount != 0 else 0
                first_trade = trade_group[0]
                combined_trade = {
                    **first_trade,
                    "amount": total_amount,
                    "price": price
                }
            else:
                combined_trade = trade_group[0]
            grouped_trades.append(combined_trade)

        # Now match opening and closing trades

        combined_trades = defaultdict(list)
        for trade in grouped_trades:
            key = (trade["underlying_symbol"], trade["strike_price"], trade["expirationDate"], trade["option_type"])
            combined_trades[key].append(trade)

        # Grouped trades now contain all trades by their unique key
        matched_trades = []
        unmatched_trades = []

        for key, trade_group in combined_trades.items():
            opens = [t for t in trade_group if t["position_effect"] == "OPENING"]
            closes = [t for t in trade_group if t["position_effect"] == "CLOSING"]

            # Sort by date to pair in order
            opens.sort(key=lambda x: x.get("date"))
            closes.sort(key=lambda x: x.get("date"))

            # Match opens and closes
            while opens and closes:
                open_trade = opens.pop(0)
                close_trade = closes.pop(0)

                if open_trade["amount"] != -close_trade["amount"] or open_trade["expirationDate"] != close_trade["expirationDate"]:
                    logger.warning(f"Unmatched trade quantities or expiration dates for {key}: Open qty {open_trade['amount']}, Close qty {close_trade['amount']}, Open exp {open_trade['expirationDate']}, Close exp {close_trade['expirationDate']}")

                
                amount = float(open_trade["amount"])
                trade_type = self.determine_trade_type(close_trade)
                price = float(open_trade.get("price", 0)) - float(close_trade.get("price", 0)) if trade_type != "ASSIGNMENT" else 0
                matched_trades.append({
                    "date": open_trade.get("date"),
                    "close_date": min(close_trade.get("date"), open_trade.get("expirationDate")), # Handle Transactions closing later than expiration in system
                    "underlying_symbol": open_trade.get("underlying_symbol"),
                    "expirationDate": open_trade.get("expirationDate"),
                    "strike_price": open_trade.get("strike_price"),
                    "symbol": open_trade.get("symbol"),
                    "price": price,
                    "open_price": open_trade.get("price"), # Added to keep track of open price
                    "close_price": close_trade.get("price"), # Added to keep track of close price
                    "amount": amount,
                    "position_effect": "MATCHED",
                    "option_type": open_trade.get("option_type"),
                    "type": trade_type
                })

            # Any unmatched trades left
            unmatched_trades.extend(opens + closes)
 
        all_trades = matched_trades + unmatched_trades
        all_trades.sort(key=lambda x: x.get("close_date"))
        for trade in all_trades:
            trade.pop("description", None)
        return all_trades

    def determine_trade_type(self, close_trade):
        trade_type = None
        if close_trade.get("type") == "RECEIVE_AND_DELIVER":
            if "Expiration" in close_trade["description"]:
                        # Handle expiration case
                trade_type = "EXPIRATION"
            elif "Assignment" in close_trade["description"]:
                        # Handle assignment case
                trade_type = "ASSIGNMENT"
            else:
                trade_type = "UNKNOWN"
        else:
            trade_type = "CLOSED"
        return trade_type