import logging
from pydantic import ValidationError

from broker.http import APIClient
from broker.exceptions import BrokerValidationError
from broker.auth import TokenProvider
from broker.data.market_data import PriceHistoryResponse, StockQuotes
from broker.data.option_data import OptionChainResponse

logger = logging.getLogger(__name__)

_MARKET_BASE = "https://api.schwabapi.com/marketdata/v1"


class MarketData(APIClient):
    """Schwab market-data sub-client — quotes, price history, option chains."""

    def __init__(self, token_provider: TokenProvider | None = None) -> None:
        super().__init__(_MARKET_BASE, token_provider)

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

    def get_price_history(
        self,
        symbol: str,
        period_type: str = "month",
        period: int = 2,
        frequency_type: str = "daily",
    ) -> PriceHistoryResponse:
        """
        Fetch OHLCV price history for a symbol.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        period_type:
            Unit of the period (``"day"``, ``"month"``, ``"year"``,
            ``"ytd"``).  Defaults to ``"month"``.
        period:
            Number of *period_type* units to fetch.  Defaults to ``2``.
        frequency_type:
            Bar frequency (``"minute"``, ``"daily"``, ``"weekly"``,
            ``"monthly"``).  Defaults to ``"daily"``.

        Returns
        -------
        PriceHistoryResponse
            Symbol and list of :class:`~data.market_data.Candle` objects.

        Raises
        ------
        BrokerAuthError / BrokerAPIError / BrokerValidationError
        """
        response_data = self._fetch_data(
            f"{self.base_url}/pricehistory",
            {
                "symbol": symbol,
                "periodType": period_type,
                "period": period,
                "frequencyType": frequency_type,
            },
        )
        try:
            return PriceHistoryResponse(**response_data)
        except ValidationError as exc:
            raise BrokerValidationError(
                f"Error parsing PriceHistoryResponse: {exc}"
            ) from exc

    def get_chain(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        strike_count: int = 10,
        strike: float | None = None,
        contract_type: str = "ALL",
    ) -> OptionChainResponse:
        """
        Fetch the option chain for a symbol.

        Parameters
        ----------
        symbol:
            Underlying ticker symbol.
        from_date:
            First expiration date to include (``YYYY-MM-DD``).
        to_date:
            Last expiration date to include (``YYYY-MM-DD``).
        strike_count:
            Number of strikes above and below the at-the-money price to
            return.  Defaults to ``10``.
        strike:
            Filter to a specific strike price.  Omit (or pass ``None``)
            to return all strikes within *strike_count*.
        contract_type:
            ``"PUT"``, ``"CALL"``, or ``"ALL"``.  Defaults to ``"ALL"``.

        Returns
        -------
        OptionChainResponse
            Full validated option chain.

        Raises
        ------
        BrokerAuthError / BrokerAPIError / BrokerValidationError
        """
        params: dict = {
            "symbol": symbol,
            "strikeCount": strike_count,
            "contractType": contract_type,
            "fromDate": from_date,
            "toDate": to_date,
        }
        if strike is not None:
            params["strike"] = strike

        response_data = self._fetch_data(f"{self.base_url}/chains", params)
        try:
            return OptionChainResponse(**response_data)
        except ValidationError as exc:
            raise BrokerValidationError(
                f"Error parsing OptionChainResponse: {exc}"
            ) from exc
