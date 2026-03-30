import logging
from typing import Optional

from broker.clients import Accounts, MarketData
from broker.auth import FileTokenProvider, RedisTokenProvider, create_token_provider
from broker.data.account_data import SecuritiesAccount, Activity
from broker.data.market_data import PriceHistoryResponse, StockQuotes
from broker.data.option_data import OptionChainResponse

logger = logging.getLogger(__name__)


class Client:
    """
    Unified Schwab API client — the main SDK entry point.

    All methods return validated Pydantic models and raise typed exceptions
    on failure (see :mod:`broker.exceptions`).

    **File-backed** (explicit credentials)::

        client = Client(
            api_key="APIKEY",
            app_secret="APP_SECRET",
            callback_url="https://127.0.0.1",
            token_path="/tmp/token.json",
        )

    **Redis-backed**::

        client = Client(
            api_key="APIKEY",
            app_secret="APP_SECRET",
            callback_url="https://127.0.0.1",
            redis_url="redis://localhost:6379",
        )

    **Env-driven** (credentials from env vars, backend from ``USE_DB``)::

        client = Client()

    **Custom token provider**::

        from broker.auth import TokenProvider

        client = Client(token_provider=VaultProvider())

    **Error handling**::

        from broker.exceptions import BrokerAuthError, BrokerAPIError, BrokerValidationError

        try:
            quote = client.get_price("AAPL")
        except BrokerAuthError:
            broker.auth.authenticate.get_access_token()
        except BrokerAPIError as e:
            print(f"HTTP {e.status_code}")
        except BrokerValidationError:
            ...
    """

    def __init__(
        self,
        api_key: str | None = None,
        app_secret: str | None = None,
        callback_url: str | None = None,
        token_path: str = "token.json",
        redis_url: str | None = None,
    ) -> None:
        if redis_url is not None:
            token_provider = RedisTokenProvider(
                redis_url=redis_url,
                app_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
            )
        elif api_key or app_secret or callback_url:
            token_provider = FileTokenProvider(
                file_path=token_path,
                app_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
            )
        else:
            token_provider = create_token_provider()

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
