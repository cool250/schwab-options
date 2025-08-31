import requests
from utils import get_access_token
from loguru import logger
from model.market_models import StockQuotes
from pydantic import ValidationError
from broker.base import APIClient

class MarketData(APIClient):
    def __init__(self):
        super().__init__("https://api.schwabapi.com/marketdata/v1/quotes")
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
        response_data = self._fetch_data(params=params)
        if response_data:
            try:
                stock_quotes = StockQuotes(**response_data)
                logger.debug(f"Successfully fetched stock quotes: {stock_quotes.model_dump_json()}")
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

