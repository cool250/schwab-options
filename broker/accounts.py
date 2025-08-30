from typing import List
import requests
from loguru import logger
from pydantic import ValidationError
from model.models import AccountHash, SecuritiesAccount, Activity
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
                response_data = response.json()
                transactions = [Activity(**item) for item in response_data]  # Validate with Pydantic
                self.log_transactions(transactions)
                logger.info(f"Total Transactions Fetched: {len(transactions)}")
                return transactions
            except ValidationError as e:
                logger.error(f"Error parsing transactions: {e}")
                return None
        else:
            logger.error(f"Error getting transactions: {response.status_code} - {response.text}")
            return None
    
    # Function to log transactions
    def log_transactions(self, transactions: List[Activity]):
        """
        Log details of transactions represented as Pydantic objects.

        Args:
            transactions (List[Activity]): List of Activity Pydantic objects.
        """
        for transaction in transactions:
            logger.info(f"Transaction: {transaction.dict()}")  # Log the entire object as a dictionary

            # Log specific fields
            logger.info(f"Activity ID: {transaction.activityId}")
            logger.info(f"Account Number: {transaction.accountNumber}")
            logger.info(f"Type: {transaction.type}")
            logger.info(f"Status: {transaction.status}")
            logger.info(f"Net Amount: {transaction.netAmount}")

            # Log transfer items if available
            if transaction.transferItems:
                for item in transaction.transferItems:
                    if item.instrument:
                        logger.info(f"  Instrument Symbol: {item.instrument.symbol}")
                        logger.info(f"  Instrument Description: {item.instrument.description}")
                    logger.info(f"  Amount: {item.amount}")
                    logger.info(f"  Cost: {item.cost}")
                    logger.info(f"  Fee Type: {item.feeType}")
                    logger.info(f"  Position Effect: {item.positionEffect}")

    def get_positions(self):
        """
        Fetch and log the account balance.
        """
        if not self.account_hash_value:
            logger.error("Account hash value is not set.")
            return None

        url = f"{self.base_url}/accounts/{self.account_hash_value}?fields=positions"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            logger.info("Account position retrieved successfully.")
            # Parse the response JSON
            response_data = response.json()

            # Extract the securitiesAccount data
            securities_account_data = response_data.get("securitiesAccount")
            if not securities_account_data:
                logger.error("Missing 'securitiesAccount' in the API response.")
                return None

            # Populate the SecuritiesAccount model
            securities_account = SecuritiesAccount(**securities_account_data)
            logger.info("Successfully populated SecuritiesAccount model.")
            self.log_securities_account(securities_account)
            return securities_account
        else:
            logger.error(f"Error getting account position: {response.status_code} - {response.text}")
            return None
        
    # Function to log securities_account object and its nested data
    def log_securities_account(self, securities_account: SecuritiesAccount):
        """
        Log details of a SecuritiesAccount object, including nested data.

        Args:
            securities_account (SecuritiesAccount): The SecuritiesAccount object to log.
        """
        # Log top-level fields
        logger.info(f"Account Number: {securities_account.accountNumber}")
        logger.info(f"Round Trips: {securities_account.roundTrips}")
        logger.info(f"Is Day Trader: {securities_account.isDayTrader}")

        # Log initial balances if available
        if securities_account.initialBalances:
            logger.info("Initial Balances:")
            logger.info(f"  Cash Balance: {securities_account.initialBalances.cashBalance}")
            logger.info(f"  Equity: {securities_account.initialBalances.equity}")
            logger.info(f"  Margin Balance: {securities_account.initialBalances.marginBalance}")

        # Log current balances if available
        if securities_account.currentBalances:
            logger.info("Current Balances:")
            logger.info(f"  Equity: {securities_account.currentBalances.equity}")
            logger.info(f"  Margin Balance: {securities_account.currentBalances.marginBalance}")

        # Log positions if available
        if securities_account.positions:
            logger.info("Positions:")
            for position in securities_account.positions:
                logger.info(f"  Short Quantity: {position.shortQuantity}")
                logger.info(f"  Average Price: {position.averagePrice}")
                logger.info(f"  Current Day Profit/Loss: {position.currentDayProfitLoss}")
                logger.info(f"  Long Quantity: {position.longQuantity}")
                logger.info(f"  Market Value: {position.marketValue}")
                if position.instrument:
                    logger.info("  Instrument:")
                    logger.info(f"    CUSIP: {position.instrument.cusip}")
                    logger.info(f"    Symbol: {position.instrument.symbol}")
                    logger.info(f"    Description: {position.instrument.description}")
                    logger.info(f"    Instrument ID: {position.instrument.instrumentId}")
                    logger.info(f"    Net Change: {position.instrument.netChange}")
                    logger.info(f"    Type: {position.instrument.type}") 
