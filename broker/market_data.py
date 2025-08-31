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

    def get_chain(self, symbol, start_date, end_date):
        """
        Fetch options chain for the given symbol and parse it using the Pydantic model.
        """
        
        params = {
            "symbol": symbol,
            "strategy": "SINGLE",
            "strike": 10,
            "startDate": start_date,
            "endDate": end_date
        }

        
        url = f"{self.base_url}/chains"
        response_data = self._fetch_data(url, params)
        if response_data:
            try:
                option_chain = OptionChainResponse(**response_data)
                logger.debug(f"Positions: {option_chain.model_dump_json()}")
                return option_chain
            except ValidationError as e:
                logger.error(f"Error parsing option chain: {e}")
        return None

    def get_put_chain(self, option_chain: OptionChainResponse):
        """
        Fetch the put options chain for the given symbol and parse it using the Pydantic model.
        """
        if option_chain and option_chain.symbol:
            logger.info(f"Put Option Chain for {option_chain.symbol} retrieved with {len(option_chain.putExpDateMap)} expiration dates.")
        return None
