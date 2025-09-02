from datetime import datetime, timedelta
from service.market import MarketService
from broker.authenticate import get_access_token
from broker.market_data import MarketData
import pytz

def chain():
    # Create an instance of MarketDataService
    service = MarketService()

    # Example usage of MarketDataService
    et_timezone = pytz.timezone("US/Eastern")
    current_date = (datetime.now(et_timezone)).strftime("%Y-%m-%d")
    future_date = (datetime.now(et_timezone) + timedelta(days=8)).strftime("%Y-%m-%d")
    print(f"From Date: {current_date}, To Date: {future_date}")
    result = service.highest_return_puts("SPY", 644, current_date, future_date)
    
    # result = service.highest_return_puts("SPY", 640, "2025-09-03", "2025-09-08")
    print("Options:", result)

def authenticate():
    # Implement authentication logic here
    get_access_token()

def price():
    service = MarketService()
    # Implement logic to fetch and display option prices
    price = service.get_ticker_price("SPY")
    print("Current Price of SPY:", price)
    # service.get_price_history("SPY", period_type='month', frequency_type='daily')


if __name__ == "__main__":
    price()