from loguru import logger
from broker.accounts import AccountsTrading
from broker.authenticate import get_access_token
from broker.market_data import MarketData
from broker.refresh_token import refresh_tokens



def account():
    acct = AccountsTrading()
    # # # acct.fetch_transactions("2025-08-26", "2025-08-28", transaction_type="TRADE")
    securities_account = acct.get_positions()

    if securities_account:
        balances = acct.get_balances(securities_account)
        logger.info(f"Balances: {balances}")

def market():
    data = MarketData()
    # stock_data = data.get_price_history("AAPL", 'year', 1)
    stock_data = data.get_stock_quote("ENPH  250919C00045000,AAPL")
    if stock_data:
        for symbol, asset in stock_data.root.items():
            if asset.quote and asset.quote.closePrice is not None:
                logger.info(f"Symbol: {symbol}, Close Price: {asset.quote.closePrice}")
    

if __name__ == "__main__":
    # get_access_token()
    refresh_tokens()

    # account()

    market()
