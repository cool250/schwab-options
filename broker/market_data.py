from loguru import logger
from model.market_models import StockQuotes
from model.option_models import OptionChainResponse
from pydantic import ValidationError
from broker.base import APIClient




class MarketData(APIClient):
    def __init__(self):
        super().__init__("https://api.schwabapi.com/marketdata/v1")
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json"
        }

    def get_price(self, symbol):
        """
        Fetch stock quotes for the given symbol(s).
        """
        params = {
            "symbols": symbol,
            "fields": "quote"
        }
        url = f"{self.base_url}/quotes"
        response_data = self._fetch_data(url, params)
        if response_data:
            try:
                stock_quotes = StockQuotes(**response_data)
                return stock_quotes
            except ValidationError as e:
                logger.error(f"Error parsing stock quotes: {e}")
        return None

    def get_price_history(self, symbol, period_type='day', period=2, frequency_type='daily'):
        """
        Fetch price history for the given symbol.
        """
        params = {
            "symbol": symbol,
            "periodType": period_type,
            "period": period,
            "frequencyType": frequency_type,
            "frequency": 1
        }
        response_data = self._fetch_data(self.base_url, params)
        return response_data

    def get_chain(self, symbol, from_date, to_date, strike_count=10, contract_type="ALL"):
        """
        Fetch options chain for the given symbol and parse it using the Pydantic model.
        """
        
        params = {
            "symbol": symbol,
            "strikeCount": strike_count,
            "contractType": contract_type,
            "fromDate": from_date,
            "toDate": to_date
        }

        
        url = f"{self.base_url}/chains"
        response_data = self._fetch_data(url, params)
        if response_data:
            try:
                option_chain = OptionChainResponse(**response_data)
                return option_chain
            except ValidationError as e:
                logger.error(f"Error parsing option chain: {e}")
        return None

