from loguru import logger
from model.market_models import PriceHistoryResponse, StockQuotes
from model.option_models import OptionChainResponse
from pydantic import ValidationError
from broker.base import APIClient


class MarketData(APIClient):
    def __init__(self):
        super().__init__("https://api.schwabapi.com/marketdata/v1")
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def get_price(self, symbol: str) -> StockQuotes | None:
        """
        Retrieve the stock price for the specified symbol(s).

        """

        url = f"{self.base_url}/quotes"
        params = {"symbols": symbol, "fields": "quote"}
        response_data = self._fetch_data(url, params)
        if response_data:
            try:
                stock_quotes = StockQuotes(**response_data)
                return stock_quotes
            except ValidationError as e:
                logger.error(f"Error parsing stock quotes: {e}")
        return None

    def get_price_history(
        self,
        symbol: str,
        period_type: str = "day",
        period: int = 2,
        frequency_type: str = "minute",
    ) -> PriceHistoryResponse | None:
        """
        Fetch the price history for a given symbol.
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

    def get_chain(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        strike_count: int = 10,
        contract_type: str = "ALL",
    ) -> OptionChainResponse | None:
        """
        Fetch the option chain for a given symbol.
        """
        url = f"{self.base_url}/chains"
        params = {
            "symbol": symbol,
            "strikeCount": strike_count,
            "contractType": contract_type,
            "fromDate": from_date,
            "toDate": to_date,
        }

        response_data = self._fetch_data(url, params)
        if response_data:
            try:
                option_chain = OptionChainResponse(**response_data)
                return option_chain
            except ValidationError as e:
                logger.error(f"Error parsing option chain: {e}")
        return None
