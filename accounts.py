import requests
from loguru import logger  # Import loguru for logging
from read_token import get_access_token
from utils import convert_to_iso8601


class AccountsTrading:
    def __init__(self):
        # Initialize access token during class instantiation
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
                self.account_hash_value = response_data[0].get("hashValue")
                logger.info(f"Account Hash Value: {self.account_hash_value}")
            except (IndexError, KeyError, ValueError) as e:
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

        # Convert input dates to ISO 8601 format
        start_date_iso = convert_to_iso8601(start_date)
        end_date_iso = convert_to_iso8601(end_date)

        url = f"{self.base_url}/accounts/{self.account_hash_value}/transactions"
        params = {"startDate": start_date_iso, "endDate": end_date_iso, "types": transaction_type}
        response = requests.get(url, headers=self.headers, params=params)

        if response.status_code == 200:
            logger.info("Transactions retrieved successfully.")
            return response.json()
        else:
            logger.error(f"Error getting transactions: {response.status_code} - {response.text}")
            return None

    def parse_transaction(self, transaction):
        """
        Parse and log details of a single transaction.
        """
        activity_id = transaction.get("activityId")
        time = transaction.get("time")
        account_number = transaction.get("accountNumber")
        transaction_type = transaction.get("type")
        net_amount = transaction.get("netAmount")
        transfer_items = transaction.get("transferItems", [])

        logger.info(f"Activity ID: {activity_id}")
        logger.info(f"Time: {time}")
        logger.info(f"Account Number: {account_number}")
        logger.info(f"Transaction Type: {transaction_type}")
        logger.info(f"Net Amount: {net_amount}")

        # Parse transfer items
        for item in transfer_items:
            self.parse_transfer_item(item)

    def parse_transfer_item(self, item):
        """
        Parse and log details of a single transfer item.
        """
        instrument = item.get("instrument", {})
        asset_type = instrument.get("assetType")
        symbol = instrument.get("symbol")
        description = instrument.get("description")
        amount = item.get("amount")
        cost = item.get("cost")
        fee_type = item.get("feeType")

        logger.info(f"  Asset Type: {asset_type}")
        logger.info(f"  Symbol: {symbol}")
        logger.info(f"  Description: {description}")
        logger.info(f"  Amount: {amount}")
        logger.info(f"  Cost: {cost}")
        logger.info(f"  Fee Type: {fee_type}")

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