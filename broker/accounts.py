import time
from typing import List
import requests
from loguru import logger
from pydantic import ValidationError
from model.models import AccountHash, SecuritiesAccount, Activity
from utils import get_access_token, convert_to_iso8601
from .refresh_token import refresh_tokens
from .logging_methods import log_transactions


class AccountsTrading:
    def __init__(self):
        self.access_token = get_access_token()
        self.account_hash_value = None
        self.base_url = "https://api.schwabapi.com/trader/v1"
        self.headers = {"Authorization": f"Bearer {self.access_token}"}
        self.get_account_number_hash_value()

    def get_account_number_hash_value(self, attempt=1, max_retries=3):
        """
        Fetch and set the account hash value from the API.
        """
        delay = 10

        url = f"{self.base_url}/accounts/accountNumbers"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            logger.debug("Retrieved account numbers successfully.")
            try:
                response_data = response.json()
                account_hash = AccountHash(**response_data[0])  # Validate with Pydantic
                self.account_hash_value = account_hash.hashValue
                logger.info(f"Account Hash Value: {self.account_hash_value}")
            except (IndexError, ValidationError) as e:
                logger.error(f"Error parsing account hash value: {e}")
        elif response.status_code == 401:  # Unauthorized (likely due to expired token)
            if attempt <= max_retries:
                logger.warning("Refresh token expired. Refreshing token and retrying...")
                refresh_tokens()
                self.access_token = get_access_token()  # Reload the new access token
                self.headers = {"Authorization": f"Bearer {self.access_token}"}  # Update headers
                return self.get_account_number_hash_value(attempt=attempt + 1, max_retries=max_retries)  # Retry the request
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
                log_transactions(transactions)
                logger.info(f"Total Transactions Fetched: {len(transactions)}")
                return transactions
            except ValidationError as e:
                logger.error(f"Error parsing transactions: {e}")
                return None
        else:
            logger.error(f"Error getting transactions: {response.status_code} - {response.text}")
            return None
    
    def get_positions(self):
        """
        Fetch and log the account balance and positions.
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
            logger.debug(f"Positions : {securities_account.model_dump_json()}")
            return securities_account
        else:
            logger.error(f"Error getting account position: {response.status_code} - {response.text}")
            return None

    def calculate_total_exposure_for_short_puts(self, securities_account: SecuritiesAccount):
        """
        Calculate and log the total exposure for short PUT option positions at the symbol level, 
        considering long PUT options to reduce the exposure.

        Args:
            securities_account (SecuritiesAccount): The SecuritiesAccount object containing positions.
        """
        puts = self.get_puts(securities_account)
        exposure_by_symbol = {}

        for put in puts:
            ticker = put["ticker"]
            strike_price = put["strike_price"]
            quantity = put["quantity"]
            exposure = put.get("exposure", 0)

            if ticker not in exposure_by_symbol:
                exposure_by_symbol[ticker] = 0

            exposure_by_symbol[ticker] += exposure
            logger.debug(f"Processed PUT for {ticker}: Strike Price: {strike_price}, Quantity: {quantity}, Exposure: {exposure}")

        for ticker, total_exposure in exposure_by_symbol.items():
            logger.debug(f"Total Exposure for {ticker}: {total_exposure}")

        return exposure_by_symbol
    
    def get_option_details(self, securities_account: SecuritiesAccount, option_type: str):
        """
        Extract details for each option position including ticker, strike price, exposure, and expiration date.

        Args:
            securities_account (SecuritiesAccount): The SecuritiesAccount object containing positions.
            option_type (str): The type of option to filter ('P' for PUT, 'C' for CALL).

        Returns:
            list: A list of dictionaries with details for each option position.
        """
        if not securities_account.positions:
            logger.debug("No positions available to extract option details.")
            return []

        option_positions_details = []
        for position in securities_account.positions:
            if position.instrument and position.instrument.assetType == "OPTION":
                symbol = position.instrument.symbol

                # Parse the option symbol to extract details
                if symbol and len(symbol) > 15 and symbol[-9] == option_type:
                    try:
                        strike_price = float(symbol[13:21]) / 1000  # Extract strike price
                        ticker = symbol[:6].strip()  # Extract ticker symbol
                        expiration_date = f"{symbol[6:8]}-{symbol[8:10]}-{symbol[10:12]}"  # Extract expiration date
                        quantity = position.longQuantity if position.longQuantity else position.shortQuantity

                        exposure = 0
                        if option_type == "P":  # Calculate exposure only for PUT options
                            if position.shortQuantity and position.shortQuantity > 0:
                                # Calculate exposure for short options
                                exposure += strike_price * position.shortQuantity * 100  # Assuming 100 shares per option contract
                            if position.longQuantity and position.longQuantity > 0:
                                # Calculate exposure for long options
                                exposure -= strike_price * position.longQuantity * 100  # Assuming 100 shares per option contract

                        option_details = {
                            "ticker": ticker,
                            "symbol": symbol,
                            "strike_price": strike_price,
                            "expiration_date": expiration_date,
                            "quantity": quantity
                        }
                        if option_type == "P":
                            option_details["exposure"] = exposure

                        option_positions_details.append(option_details)
                        logger.debug(f"Option Position: {ticker}, Strike: {strike_price}, Expiration: {expiration_date}, Quantity: {quantity}, Exposure: {exposure if option_type == 'P' else 'N/A'}")
                    except ValueError as e:
                        logger.error(f"Error parsing option symbol {symbol}: {e}")

        return option_positions_details

    def get_puts(self, securities_account: SecuritiesAccount):
        """
        Extract details for PUT option positions.

        Args:
            securities_account (SecuritiesAccount): The SecuritiesAccount object containing positions.

        Returns:
            list: A list of dictionaries with details for each PUT option position.
        """
        return self.get_option_details(securities_account, option_type="P")

    def get_calls(self, securities_account: SecuritiesAccount):
        """
        Extract details for CALL option positions.

        Args:
            securities_account (SecuritiesAccount): The SecuritiesAccount object containing positions.

        Returns:
            list: A list of dictionaries with details for each CALL option position.
        """
        return self.get_option_details(securities_account, option_type="C")

