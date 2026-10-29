import logging
from typing import Optional
from pydantic import ValidationError

from broker.schwab.http import BaseClient
from broker.schwab.exceptions import BrokerAPIError, BrokerValidationError
from broker.schwab.auth import TokenProvider
from broker.request_context import get_selected_account
from broker.schwab.data.account_data import AccountHash, SecuritiesAccount, Activity
from utils import convert_to_iso8601

logger = logging.getLogger(__name__)


class Accounts(BaseClient):
    """Schwab account sub-client — positions and transaction history."""

    _ACCOUNT_BASE = "https://api.schwabapi.com/trader/v1"

    def __init__(self, token_provider: TokenProvider | None = None) -> None:
        super().__init__(self._ACCOUNT_BASE, token_provider)
        self._account_hash_value: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _initialize_account_hash(self) -> None:
        """Fetch and cache the account hash (called lazily on first use).

        When the login covers several accounts, uses the one this request's
        user picked in Settings (get_selected_account); if none is picked —
        or the picked one is no longer authorized — the first Schwab lists."""
        response_data = self._fetch_data(f"{self.base_url}/accounts/accountNumbers")
        try:
            selected = get_selected_account()
            entry = next((e for e in response_data if selected and e.get("accountNumber") == selected), response_data[0])
            account_hash = AccountHash(**entry)
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

    def list_accounts(self) -> list[dict]:
        """Every account the login covers, in Schwab's order:
        [{"accountNumber", "hashValue", "type", "liquidationValue"}]
        — enough to tell them apart in an account picker. /accounts is asked
        without fields=positions: balances only, so the picker doesn't pull
        every holding of every account."""
        numbers = self._fetch_data(f"{self.base_url}/accounts/accountNumbers") or []
        details = self._fetch_data(f"{self.base_url}/accounts") or []
        by_number = {}
        for item in details:
            account = item.get("securitiesAccount") or {}
            by_number[account.get("accountNumber")] = account
        out = []
        for entry in numbers:
            account = by_number.get(entry.get("accountNumber"), {})
            out.append({
                "accountNumber": entry.get("accountNumber"),
                "hashValue": entry.get("hashValue"),
                "type": account.get("type"),
                "liquidationValue": (account.get("currentBalances") or {}).get("liquidationValue"),
            })
        return out

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
