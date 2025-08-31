import time
from typing import List
import requests
from loguru import logger
from pydantic import ValidationError
from broker.base import APIClient
from model.account_models import AccountHash, SecuritiesAccount, Activity
from utils import get_access_token, convert_to_iso8601
from .refresh_token import refresh_tokens
from .logging_methods import log_transactions



class AccountsTrading(APIClient):
    def __init__(self):
        super().__init__("https://api.schwabapi.com/trader/v1")
        self.account_hash_value = None
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
        elif attempt <= max_retries:
            logger.warning("Token expired. Refreshing token and retrying...")
            self.get_account_number_hash_value(attempt + 1, max_retries)
        else:
            logger.error("Failed to retrieve account hash value after retries.")

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

        url = f"{self.base_url}/accounts/{self.account_hash_value}"
        params = {"fields": "positions"}
        response_data = self._fetch_data(url, params)

        if response_data:
            securities_account_data = response_data.get("securitiesAccount")
            if securities_account_data:
                try:
                    securities_account = SecuritiesAccount(**securities_account_data)
                    logger.debug(f"Positions: {securities_account.model_dump_json()}")
                    return securities_account
                except ValidationError as e:
                    logger.error(f"Error parsing securities account: {e}")
        logger.error("Failed to retrieve positions.")
        return None

    def get_balances(self, securities_account: SecuritiesAccount):
        """
        Fetch and log the account balances.
        """
        if not securities_account:
            logger.error("Securities account is not available.")
            return None

        balances = {
            "margin": securities_account.initialBalances.margin if securities_account.initialBalances else None
        }
        logger.debug(f"Account Balances: {balances}")
        return balances
    
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

        def parse_option_symbol(symbol):
            try:
                strike_price = float(symbol[13:21]) / 1000
                ticker = symbol[:6].strip()
                expiration_date = f"{symbol[6:8]}-{symbol[8:10]}-{symbol[10:12]}"
                return ticker, strike_price, expiration_date
            except ValueError as e:
                logger.error(f"Error parsing option symbol {symbol}: {e}")
                return None, None, None

        option_positions_details = []
        for position in securities_account.positions:
            if position.instrument and position.instrument.assetType == "OPTION":
                symbol = position.instrument.symbol
                if symbol and len(symbol) > 15 and symbol[-9] == option_type:
                    ticker, strike_price, expiration_date = parse_option_symbol(symbol)
                    if ticker:
                        quantity = position.longQuantity or position.shortQuantity
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
                            "strike_price": f"${strike_price:,.2f}",
                            "expiration_date": expiration_date,
                            "quantity": quantity,
                            "trade_price": f"${position.averagePrice:,.2f}" if position.averagePrice else None
                        }
                        if option_type == "P":
                            option_details["exposure"] = exposure                        
                        
                        option_positions_details.append(option_details)
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
            exposure = put.get("exposure", 0)
            exposure_by_symbol[ticker] = exposure_by_symbol.get(ticker, 0) + exposure

        logger.debug(f"Total Exposure: {exposure_by_symbol}")
        return exposure_by_symbol

