import logging
from typing import Optional

from broker.accounts import Accounts
from broker.market_data import MarketData
from data.account_data import SecuritiesAccount, Activity
from data.market_data import PriceHistoryResponse, StockQuotes
from data.option_data import OptionChainResponse

logger = logging.getLogger(__name__)


class Client:
    """
    Unified Schwab API client.

    Wraps all broker sub-clients and exposes every supported API call
    through a single object.

    Usage::

        client = Client()

        # Market data
        quote   = client.get_price("AAPL")
        history = client.get_price_history("AAPL")
        chain   = client.get_chain("AAPL", "2026-03-01", "2026-04-01")

        # Account
        positions    = client.fetch_positions()
        transactions = client.fetch_transactions("2026-01-01", "2026-03-19")
    """

    def __init__(self) -> None:
        self._accounts = Accounts()
        self._market_data = MarketData()

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------

    def get_price(self, symbol: str) -> StockQuotes | None:
        """Retrieve the current quote for one or more symbols."""
        return self._market_data.get_price(symbol)

    def get_price_history(
        self,
        symbol: str,
        period_type: str = "month",
        period: int = 2,
        frequency_type: str = "daily",
    ) -> PriceHistoryResponse | None:
        """Fetch OHLCV price history for a symbol."""
        return self._market_data.get_price_history(
            symbol, period_type, period, frequency_type
        )

    def get_chain(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        strike_count: int = 10,
        strike: float = 0.0,
        contract_type: str = "ALL",
    ) -> OptionChainResponse | None:
        """Fetch the option chain for a symbol."""
        return self._market_data.get_chain(
            symbol, from_date, to_date, strike_count, strike, contract_type
        )

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def fetch_positions(self) -> Optional[SecuritiesAccount]:
        """Retrieve current account positions."""
        return self._accounts.fetch_positions()

    def fetch_transactions(
        self,
        start_date: str,
        end_date: str,
        symbol: Optional[str] = None,
    ) -> Optional[list[Activity]]:
        """Fetch account transactions for a date range."""
        return self._accounts.fetch_transactions(start_date, end_date, symbol)
