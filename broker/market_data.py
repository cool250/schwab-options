from loguru import logger
from model.market_models import PriceHistoryResponse, StockQuotes
from model.option_models import OptionChainResponse
from pydantic import ValidationError, BaseModel
from typing import List
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

    def get_price_history(self, symbol, period_type='day', period=2, frequency_type='minute'):
        """
        Fetch price history for the given symbol.
        """
        url = f"{self.base_url}/pricehistory"

        params = {
            "symbol": symbol,
            "periodType": period_type,
            "period": period,
            "frequencyType": frequency_type,
        }
        response_data = self._fetch_data(url, params)
        if response_data:
            try:
                market_data_response = PriceHistoryResponse(**response_data)
                return market_data_response
            except ValidationError as e:
                logger.error(f"Error parsing price history: {e}")
        return None

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

