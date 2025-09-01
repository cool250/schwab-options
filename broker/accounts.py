from loguru import logger
from pydantic import ValidationError
from typing import Optional
from broker.base import APIClient
from model.account_models import AccountHash, SecuritiesAccount, Activity
from utils import convert_to_iso8601
from .logging_methods import log_transactions



class AccountsTrading(APIClient):
    def __init__(self):
        super().__init__("https://api.schwabapi.com/trader/v1")
        self.account: Optional[SecuritiesAccount] = None
        self.account_hash_value: Optional[str] = None
        self._initialize_account_hash()

    def _initialize_account_hash(self):
        """Initialize the account hash value by fetching it from the API."""
        url = f"{self.base_url}/accounts/accountNumbers"
        response_data = self._fetch_data(url)

        if not response_data:
            logger.error("Failed to retrieve account hash value after retries.")
            return

        try:
            account_hash = AccountHash(**response_data[0])
            self.account_hash_value = account_hash.hashValue
            logger.info(f"Account Hash Value: {self.account_hash_value}")
        except (IndexError, ValidationError) as e:
            logger.error(f"Error parsing account hash value: {e}")

    def get_account(self):
        """Retrieve the account details, fetching positions if necessary."""
        if not self.account:
            self.account = self._fetch_positions()
            if self.account is None:
                logger.error("Failed to retrieve account positions. Account is None.")
                raise ValueError("Failed to retrieve account positions. Account is None.")
        return self.account

    def fetch_transactions(self, start_date, end_date, transaction_type=None):
        """Fetch transactions for the given date range and transaction type."""

        start_date_iso = convert_to_iso8601(start_date)
        end_date_iso = convert_to_iso8601(end_date)

        url = f"{self.base_url}/accounts/{self.account_hash_value}/transactions"
        params = {"startDate": start_date_iso, "endDate": end_date_iso, "types": transaction_type}
        response_data = super()._fetch_data(url, params)

        if not response_data:
            logger.error("Failed to retrieve transactions.")
            return None

        try:
            transactions = [Activity(**item) for item in response_data]
            log_transactions(transactions)
            logger.info(f"Total Transactions Fetched: {len(transactions)}")
            return transactions
        except ValidationError as e:
            logger.error(f"Error parsing transactions: {e}")
            return None

    def _fetch_positions(self):
        """Fetch and log the account balance and positions."""

        url = f"{self.base_url}/accounts/{self.account_hash_value}"
        params = {"fields": "positions"}
        response_data = super()._fetch_data(url, params)

        if not response_data:
            logger.error("Failed to retrieve positions.")
            return None

        securities_account_data = response_data.get("securitiesAccount")
        if not securities_account_data:
            logger.error("No securities account data found in response.")
            return None

        try:
            securities_account = SecuritiesAccount(**securities_account_data)
            self.account = securities_account
            return securities_account
        except ValidationError as e:
            logger.error(f"Error parsing securities account: {e}")
            return None



