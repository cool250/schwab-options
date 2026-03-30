import logging
from typing import Optional
from pydantic import ValidationError

from broker.base import APIClient
from broker.exceptions import BrokerAPIError, BrokerValidationError
from broker.token_provider import TokenProvider
from data.account_data import AccountHash, SecuritiesAccount, Activity
from utils import convert_to_iso8601

logger = logging.getLogger(__name__)

_TRADER_BASE = "https://api.schwabapi.com/trader/v1"


class Accounts(APIClient):
    """Schwab account sub-client — positions and transaction history."""

    def __init__(self, token_provider: TokenProvider | None = None) -> None:
        super().__init__(_TRADER_BASE, token_provider)
        self._account_hash_value: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _initialize_account_hash(self) -> None:
        """Fetch and cache the account hash (called lazily on first use)."""
        response_data = self._fetch_data(f"{self.base_url}/accounts/accountNumbers")
        try:
            account_hash = AccountHash(**response_data[0])
            self._account_hash_value = account_hash.hashValue
        except (IndexError, ValidationError) as exc:
            raise BrokerValidationError(
                f"Could not parse account hash from response: {exc}"
            ) from exc

    @property
    def _account_hash(self) -> str:
        """Return the cached account hash, initialising it on first access."""
        if self._account_hash_value is None:
            self._initialize_account_hash()
        return self._account_hash_value  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_positions(self) -> SecuritiesAccount:
        """
        Retrieve current account positions.

        Returns
        -------
        SecuritiesAccount
            Validated Pydantic model containing positions and balances.

        Raises
        ------
        BrokerAuthError
            On authentication failure.
        BrokerAPIError
            On HTTP error after retries, or if the response is missing the
            ``securitiesAccount`` field.
        BrokerValidationError
            When the response cannot be parsed into :class:`SecuritiesAccount`.
        """
        url = f"{self.base_url}/accounts/{self._account_hash}"
        response_data = self._fetch_data(url, {"fields": "positions"})

        securities_account_data = response_data.get("securitiesAccount")
        if not securities_account_data:
            raise BrokerAPIError(
                "Response missing expected 'securitiesAccount' field."
            )

        try:
            return SecuritiesAccount(**securities_account_data)
        except ValidationError as exc:
            raise BrokerValidationError(
                f"Error parsing SecuritiesAccount: {exc}"
            ) from exc

    def fetch_transactions(
        self,
        start_date: str,
        end_date: str,
        symbol: Optional[str] = None,
    ) -> list[Activity]:
        """
        Fetch account transactions for a date range.

        Parameters
        ----------
        start_date:
            Start date in ``YYYY-MM-DD`` format.
        end_date:
            End date in ``YYYY-MM-DD`` format.
        symbol:
            Optional ticker to narrow results to a single underlying.

        Returns
        -------
        list[Activity]
            A (possibly empty) list of validated transaction records.

        Raises
        ------
        BrokerAuthError / BrokerAPIError / BrokerValidationError
        """
        params: dict = {
            "startDate": convert_to_iso8601(start_date),
            "endDate": convert_to_iso8601(end_date),
        }
        if symbol is not None:
            params["symbol"] = symbol

        url = f"{self.base_url}/accounts/{self._account_hash}/transactions"
        response_data = self._fetch_data(url, params)

        try:
            return [Activity(**item) for item in response_data]
        except ValidationError as exc:
            raise BrokerValidationError(
                f"Error parsing Activity list: {exc}"
            ) from exc
