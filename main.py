from datetime import datetime, timedelta
from service.option_chain import OptionChainService
from broker.authenticate import get_access_token
from broker.market_data import MarketData

def chain():
    # Create an instance of OptionChainService
    service = OptionChainService()

    # Example usage of OptionChainService
    current_date = datetime.now().strftime("%Y-%m-%d")
    future_date = (datetime.now() + timedelta(days=8)).strftime("%Y-%m-%d")
    print(f"From Date: {current_date}, To Date: {future_date}")
    result = service.highest_return_puts("SPY", 644, current_date, future_date)
    
    # result = service.highest_return_puts("SPY", 640, "2025-09-03", "2025-09-08")
    print("Options:", result)

def authenticate():
    # Implement authentication logic here
    get_access_token()

def price():
    market_data = MarketData()
    # Implement logic to fetch and display option prices
    market_data.get_price("AAPL, MSFT")


if __name__ == "__main__":
    chain()