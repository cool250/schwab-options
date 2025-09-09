
from collections import defaultdict
from loguru import logger
from broker.accounts import AccountsTrading
from broker.market_data import MarketData
from model.account_models import SecuritiesAccount

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
    
    def get_option_transactions(self, start_date: str, end_date: str, ticker: str, contract_type: str = "ALL"):
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
                        if ticker and ticker != underlyingSymbol:
                            continue
                        symbol = getattr(item.instrument, "symbol", "")  # Default to empty string if None
                        price = getattr(item.instrument, "closingPrice", None)
                        strikePrice = getattr(item.instrument, "strikePrice", None)
                        optionType = getattr(item.instrument, "putCall", None)
                        ticker, strike_price, expiration_date = parse_option_symbol(symbol)
                        option_transactions.append({
                            "date": getattr(transaction, "tradeDate", None),
                            "symbol": symbol,
                            "price": price,
                            "underlying_symbol": underlyingSymbol,
                            "strike_price": strikePrice,
                            "option_type": optionType,
                            "expirationDate": expiration_date,
                            "ticker": ticker,
                            "qty": getattr(item, "amount", 0),
                            "position_effect": getattr(item, "positionEffect", None),

                        })
        # option_transactions = self.match_open_close_trades(option_transactions)
        return option_transactions

    def match_open_close_trades(self, trades):
        # Group trades by contract identity
        grouped = defaultdict(list)
        for trade in trades:
            key = (trade["underlying_symbol"], trade["strike_price"], trade["expirationDate"])
            grouped[key].append(trade)

        matched_trades = []
        unmatched_trades = []

        for key, trade_group in grouped.items():
            opens = [t for t in trade_group if t["position_effect"] == "OPENING"]
            closes = [t for t in trade_group if t["position_effect"] == "CLOSING"]

            # Sort by date to pair in order
            opens.sort(key=lambda x: x.get("date"))
            closes.sort(key=lambda x: x.get("date"))

            # Match opens and closes
            while opens and closes:
                open_trade = opens.pop(0)
                close_trade = closes.pop(0)

                matched_qty = min(open_trade["qty"], close_trade["qty"])

                matched_trades.append({
                    "underlying_symbol": key[0],
                    "strike_price": key[1],
                    "expirationDate": key[2],
                    "open_date": open_trade.get("date"),
                    "close_date": close_trade.get("date"),
                    "symbol": open_trade.get("symbol"),
                    "option_type": open_trade.get("option_type"),
                    "ticker": open_trade.get("ticker"),
                    "open_price": open_trade.get("price"),
                    "close_price": close_trade.get("price"),
                    "qty": matched_qty,
                    "net": (close_trade.get("price", 0) - open_trade.get("price", 0))
                })

                # Adjust remaining qty
                if open_trade["qty"] > matched_qty:
                    open_trade["qty"] -= matched_qty
                    opens.insert(0, open_trade)
                elif close_trade["qty"] > matched_qty:
                    close_trade["qty"] -= matched_qty
                    closes.insert(0, close_trade)

            # Any unmatched trades left
            unmatched_trades.extend(opens + closes)

        return matched_trades + unmatched_trades