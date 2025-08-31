from broker.accounts import AccountsTrading
from broker.authenticate import get_access_token
from broker.market_data import MarketData
from broker.refresh_token import refresh_tokens



if __name__ == "__main__":
    # get_access_token()
    refresh_tokens()

    # acct = AccountsTrading()
    # # # acct.fetch_transactions("2025-08-26", "2025-08-28", transaction_type="TRADE")
    # securities_account = acct.get_positions()

    data = MarketData()
    # stock_data = data.get_price_history("AAPL", 'year', 1)
    stock_data = data.get_stock_quote("SPY")
