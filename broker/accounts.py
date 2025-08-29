import requests
from loguru import logger
from pydantic import ValidationError
from model.models import AccountHash, Transaction, TransferItem
from utils import get_access_token, convert_to_iso8601


class AccountsTrading:
    def __init__(self):
        self.access_token = get_access_token()
        self.account_hash_value = None
        self.base_url = "https://api.schwabapi.com/trader/v1"
        self.headers = {"Authorization": f"Bearer {self.access_token}"}
        self.get_account_number_hash_value()

    def get_account_number_hash_value(self):
        """
        Fetch and set the account hash value from the API.
        """
        url = f"{self.base_url}/accounts/accountNumbers"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            logger.info("Retrieved account numbers successfully.")
            try:
                response_data = response.json()
                account_hash = AccountHash(**response_data[0])  # Validate with Pydantic
                self.account_hash_value = account_hash.hashValue
                logger.info(f"Account Hash Value: {self.account_hash_value}")
            except (IndexError, ValidationError) as e:
                logger.error(f"Error parsing account hash value: {e}")
        else:
            logger.error(f"Error getting account hash: {response.status_code} - {response.text}")

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
        response = requests.get(url, headers=self.headers, params=params)

        if response.status_code == 200:
            logger.info("Transactions retrieved successfully.")
            try:
                transactions = [Transaction(**txn) for txn in response.json()]  # Validate with Pydantic
                return transactions
            except ValidationError as e:
                logger.error(f"Error parsing transactions: {e}")
                return None
        else:
            logger.error(f"Error getting transactions: {response.status_code} - {response.text}")
            return None

    def parse_transaction(self, transaction: Transaction):
        """
        Parse and log details of a single transaction.
        """
        logger.info(f"Activity ID: {transaction.activityId}")
        logger.info(f"Time: {transaction.time}")
        logger.info(f"Account Number: {transaction.accountNumber}")
        logger.info(f"Transaction Type: {transaction.type}")
        logger.info(f"Net Amount: {transaction.netAmount}")

        for item in transaction.transferItems:
            self.parse_transfer_item(item)

    def parse_transfer_item(self, item: TransferItem):
        """
        Parse and log details of a single transfer item.
        """
        instrument = item.instrument
        if instrument:
            logger.info(f"  Asset Type: {instrument.assetType}")
            logger.info(f"  Symbol: {instrument.symbol}")
            logger.info(f"  Description: {instrument.description}")
            logger.info(f"  Amount: {instrument.amount}")
            logger.info(f"  Cost: {instrument.cost}")
            logger.info(f"  Fee Type: {instrument.feeType}")

    def get_transactions(self, start_date, end_date, transaction_type=None):
        """
        Fetch and log transactions for the given date range and transaction type.
        """
        transactions = self.fetch_transactions(start_date, end_date, transaction_type)
        if transactions:
            for transaction in transactions:
                self.parse_transaction(transaction)
        else:
            logger.error("No transactions to display.")


if __name__ == "__main__":
    acct = AccountsTrading()
    acct.get_transactions("2024-03-28", "2024-04-01", transaction_type="TRADE")