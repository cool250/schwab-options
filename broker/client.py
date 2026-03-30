import logging
from typing import Optional

from broker.accounts import Accounts
from broker.market_data import MarketData
from broker.token_provider import TokenProvider
from data.account_data import SecuritiesAccount, Activity
from data.market_data import PriceHistoryResponse, StockQuotes
from data.option_data import OptionChainResponse

logger = logging.getLogger(__name__)


class Client:
    """
    Unified Schwab API client — the main SDK entry point.

    All methods return validated Pydantic models and raise typed exceptions
    on failure (see :mod:`broker.exceptions`).

    **Default usage** (tokens from env / ``token.json`` / Redis)::

        from broker import Client

        client = Client()
        quote   = client.get_price("AAPL")
        history = client.get_price_history("AAPL")
        chain   = client.get_chain("AAPL", "2026-03-01", "2026-04-01")
        pos     = client.fetch_positions()
        txns    = client.fetch_transactions("2026-01-01", "2026-03-29")

    **Custom token provider**::

        from broker import Client
        from broker.token_provider import TokenProvider

        class VaultProvider(TokenProvider):
            def get_access_token(self):   return vault.get("schwab_access_token")
            def get_refresh_token(self):  return vault.get("schwab_refresh_token")
            def save_tokens(self, data):  vault.put("schwab_access_token", data["access_token"])
                                          vault.put("schwab_refresh_token", data["refresh_token"])
            def get_app_credentials(self): return vault.get("app_key"), vault.get("app_secret"), vault.get("callback")

        client = Client(token_provider=VaultProvider())

    **Error handling**::

        from broker.exceptions import BrokerAuthError, BrokerAPIError, BrokerValidationError

        try:
            quote = client.get_price("AAPL")
        except BrokerAuthError:
            # Refresh token expired — re-authenticate
            broker.authenticate.get_access_token()
        except BrokerAPIError as e:
            print(f"HTTP {e.status_code}")
        except BrokerValidationError:
            # API schema changed
            ...
    """

    def __init__(self, token_provider: TokenProvider | None = None) -> None:
        self._accounts = Accounts(token_provider)
        self._market_data = MarketData(token_provider)

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------

    def get_price(self, symbol: str) -> StockQuotes:
        """Current quote for *symbol* (or comma-separated list of symbols)."""
        return self._market_data.get_price(symbol)

    def get_price_history(
        self,
        symbol: str,
        period_type: str = "month",
        period: int = 2,
        frequency_type: str = "daily",
    ) -> PriceHistoryResponse:
        """OHLCV price history for *symbol*."""
        return self._market_data.get_price_history(
            symbol, period_type, period, frequency_type
        )

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
        Option chain for *symbol* between *from_date* and *to_date*.

        Pass ``strike=<price>`` to filter to a specific strike.
        Omit (or pass ``None``) to return all strikes within *strike_count*.
        """
        return self._market_data.get_chain(
            symbol, from_date, to_date, strike_count, strike, contract_type
        )

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def fetch_positions(self) -> SecuritiesAccount:
        """Current account positions and balances."""
        return self._accounts.fetch_positions()

    def fetch_transactions(
        self,
        start_date: str,
        end_date: str,
        symbol: Optional[str] = None,
    ) -> list[Activity]:
        """
        Account transactions for *start_date* … *end_date* (``YYYY-MM-DD``).

        Optionally narrow to a single underlying with *symbol*.
        """
        return self._accounts.fetch_transactions(start_date, end_date, symbol)
