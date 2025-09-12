from collections import defaultdict
from loguru import logger
from broker.accounts import AccountsTrading
from broker.market_data import MarketData
from model.account_models import SecuritiesAccount
from utils.utils import get_date_string

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
        transactions = self.accounts_trading.fetch_transactions(start_date=start_date, end_date=end_date)
        if transactions is None or len(transactions) == 0:
            logger.error("No transactions found for the given date range.")
            return []

        option_transactions = []
        for transaction in transactions:
            transfer_items = getattr(transaction, "transferItems", None)
            if transfer_items:
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
                        price = getattr(item, "price", None)
                        strikePrice = getattr(item.instrument, "strikePrice", None)
                        amount = item.amount
                        total = -price * amount * 100
                        if symbol is not None:
                            ticker, strike_price, expiration_date = parse_option_symbol(symbol)
                        else:
                            # Assign empty strings as default values to match the expected type
                            ticker, strike_price, expiration_date = "", "", ""
                        option_transactions.append({
                            "date": get_date_string(getattr(transaction, "tradeDate", "")) if getattr(transaction, "tradeDate", None) else "",
                            "close_date": None,
                            "underlying_symbol": underlyingSymbol,
                            "expirationDate": expiration_date,
                            "strike_price": strikePrice,
                            "symbol": symbol,
                            "price": price,
                            "ticker": ticker,
                            "amount": amount,
                            "total": total,
                            "position_effect": getattr(item, "positionEffect", None),
                            "option_type": optionType,
                        })
        option_transactions = self.match_open_close_trades(option_transactions)
        return option_transactions

    def match_open_close_trades(self, trades):
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
        # Combine trades with the same key by summing quantities and keeping the price of the first trade
        for key, trade_group in position_grouped.items():
            if len(trade_group) > 1:
                total_amount = sum(t["amount"] for t in trade_group)
                first_trade = trade_group[0]
                combined_trade = {
                    **first_trade,
                    "amount": total_amount
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

                price = (close_trade.get("price", 0) - open_trade.get("price", 0))
                amount = open_trade["amount"]
                total = -price * amount * 100
                matched_trades.append({
                    "date": open_trade.get("date"),
                    "close_date": close_trade.get("date"),
                    "underlying_symbol": key[0],
                    "expirationDate": key[2],
                    "strike_price": key[1],
                    "symbol": open_trade.get("symbol"),
                    "price": price,
                    "ticker": open_trade.get("ticker"),
                    "amount": amount,
                    "total": total,
                    "position_effect": "MATCHED",
                })

            # Any unmatched trades left
            unmatched_trades.extend(opens + closes)
            all_trades = matched_trades + unmatched_trades
            all_trades.sort(key=lambda x: x.get("date"))

        return all_trades