from datetime import datetime, timedelta
from service.market import MarketService
from service.transactions import TransactionService
from broker.authenticate import get_access_token
from service.position import PositionService
from service.agent import AgentService

import pytz

def chain():
    # Create an instance of MarketDataService
    service = MarketService()

    # Example usage of MarketDataService
    et_timezone = pytz.timezone("US/Eastern")
    current_date = (datetime.now(et_timezone)).strftime("%Y-%m-%d")
    future_date = (datetime.now(et_timezone) + timedelta(days=8)).strftime("%Y-%m-%d")
    print(f"From Date: {current_date}, To Date: {future_date}")
    result = service.highest_return("SPY", 644, current_date, future_date)
    
    # result = service.highest_return_puts("SPY", 640, "2025-09-03", "2025-09-08")
    print("Options:", result)

def authenticate():
    # Implement authentication logic here
    get_access_token()

def price():
    service = MarketService()
    # Implement logic to fetch and display option prices
    price = service.get_ticker_price("CRM")
    print("Current Price of Ticker:", price)
    # service.get_price_history("SPY", period_type='month', frequency_type='daily')

def price_history():
    service = MarketService()
    candles = []
    # Implement logic to fetch and display option prices
    price_history = service.get_price_history("CRM", period_type='month', frequency_type='daily', period=1)
    print(f"Total records: {len(price_history)}")
    print("\nTop 10 records:")
    if price_history:
        for day in price_history:
            # Convert epoch timestamp to readable date
            readable_date = day.get_datetime().strftime("%Y-%m-%d")
            candles.append({
                "date": readable_date,
                "open": day.open,
                "high": day.high,
                "low": day.low,
                "close": day.close,
                "volume": day.volume
            })
    print(candles)

def position():
    service = PositionService()
    positions = service.get_positions()

def transaction():
    service = TransactionService()
    # transactions = service.get_transaction_history("2025-03-01", "2025-03-30")

    option_transactions = service.get_option_transactions("SPY", "2025-03-01", "2025-03-30")
    print("Option Transactions:", option_transactions)

def llm():
    service = AgentService()
    query = "Get the option chain for SPY PUTs with strike price around current price"
    response = service.invoke_llm(query)
    print("LLM Response:", response)


if __name__ == "__main__":
    authenticate()
    # price_history()
    # transaction()
    # position()