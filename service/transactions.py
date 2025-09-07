
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