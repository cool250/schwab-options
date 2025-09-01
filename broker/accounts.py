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
        self.get_account_number_hash_value()

    def get_account_number_hash_value(self, attempt=1, max_retries=3):
        """
        Fetch and set the account hash value from the API.
        """
        url = f"{self.base_url}/accounts/accountNumbers"
        response_data = self._fetch_data(url)

        if response_data:
            try:
                account_hash = AccountHash(**response_data[0])
                self.account_hash_value = account_hash.hashValue
                logger.info(f"Account Hash Value: {self.account_hash_value}")
            except (IndexError, ValidationError) as e:
                logger.error(f"Error parsing account hash value: {e}")
        else:
            logger.error("Failed to retrieve account hash value after retries.")

    def get_account(self):
        if not self.account:
            self.account = self.fetch_positions()
            if self.account is None:
                logger.error("Failed to retrieve account positions. Account is None.")
                raise ValueError("Failed to retrieve account positions. Account is None.")
        return self.account

    def fetch_transactions(self, start_date, end_date, transaction_type=None):
        """
        Fetch transactions for the given date range and transaction type.
        """
        if not self.account_hash_value:
            logger.error("Account hash value is not set.")
            return None

        start_date_iso = convert_to_iso8601(start_date)
        end_date_iso = convert_to_iso8601(end_date)

        url = f"{self.base_url}/accounts/{self.account_hash_value}/transactions"
        params = {"startDate": start_date_iso, "endDate": end_date_iso, "types": transaction_type}
        response_data = self._fetch_data(url, params)

        if response_data:
            logger.info("Transactions retrieved successfully.")
            try:
                transactions = [Activity(**item) for item in response_data]
                log_transactions(transactions)
                logger.info(f"Total Transactions Fetched: {len(transactions)}")
                return transactions
            except ValidationError as e:
                logger.error(f"Error parsing transactions: {e}")
                return None
        logger.error("Failed to retrieve transactions.")
        return None
    
    def fetch_positions(self):
        """
        Fetch and log the account balance and positions.
        """
        if not self.account_hash_value:
            logger.error("Account hash value is not set.")
            return None

        url = f"{self.base_url}/accounts/{self.account_hash_value}"
        params = {"fields": "positions"}
        response_data = self._fetch_data(url, params)

        if response_data:
            securities_account_data = response_data.get("securitiesAccount")
            if securities_account_data:
                try:
                    securities_account = SecuritiesAccount(**securities_account_data)
                    self.account = securities_account 
                    return securities_account
                except ValidationError as e:
                    logger.error(f"Error parsing securities account: {e}")
        logger.error("Failed to retrieve positions.")
        return None
    
    

