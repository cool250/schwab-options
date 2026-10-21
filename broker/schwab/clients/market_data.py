import logging
from pydantic import ValidationError

from broker.schwab.http import BaseClient
from broker.schwab.exceptions import BrokerValidationError
from broker.schwab.auth import TokenProvider
from broker.schwab.data.market_data import StockQuotes

logger = logging.getLogger(__name__)


class MarketData(BaseClient):
    """Schwab market-data sub-client — quotes (all the app uses Schwab market data for)."""

    _MARKET_BASE = "https://api.schwabapi.com/marketdata/v1"

    def __init__(self, token_provider: TokenProvider | None = None) -> None:
        super().__init__(self._MARKET_BASE, token_provider)

    def get_price(self, symbol: str) -> StockQuotes:
        """
        Retrieve the current quote for one or more symbols.

        Parameters
        ----------
        symbol:
            Ticker symbol or comma-separated list of symbols.

        Returns
        -------
        StockQuotes
            Validated quote data keyed by symbol.

        Raises
        ------
        BrokerAuthError / BrokerAPIError / BrokerValidationError
        """
        response_data = self._fetch_data(
            f"{self.base_url}/quotes",
            {"symbols": symbol, "fields": "quote"},
        )
        try:
            return StockQuotes(**response_data)
        except ValidationError as exc:
            raise BrokerValidationError(f"Error parsing StockQuotes: {exc}") from exc
