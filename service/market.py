from datetime import datetime, timedelta
import pytz
import logging

from broker import Client
from broker.exceptions import BrokerError

logger = logging.getLogger(__name__)


class MarketService:
    def __init__(self):
        self.client = Client()

    def highest_return(self, symbol: str, strike: float, from_date: str, to_date: str, contract_type="PUT"):
        """
        Finds the put option with the highest annualized return for a given symbol and strike price.

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.
            strike (float): The strike price to filter options.
            from_date (str): The start date for option chain data (format: 'YYYY-MM-DD').
            to_date (str): The end date for option chain data (format: 'YYYY-MM-DD').

        Returns:
            tuple: (max_return (float), best_expiration_date (str), best_price (float))
                Returns None if no suitable option is found.
        """
        try:
            option_chain = self.client.get_chain(symbol, from_date, to_date, strike_count=20, contract_type=contract_type)
        except BrokerError as e:
            logger.error("Failed to fetch option chain for %s: %s", symbol, e)
            return None

        results = self._process_option_chain(option_chain, strike, contract_type)
        if not results:
            return None

        best_option = max(results, key=lambda x: x["annualized_return"], default=None)
        if not best_option:
            return None

        return best_option["annualized_return"], best_option["expiration_date"], best_option["price"]

    def get_all_expiration_dates(self, symbol: str, strike: float, from_date: str, to_date: str, contract_type="PUT"):
        """
        Get all expiration dates for a given strike price along with their prices and returns.

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.
            strike (float): The strike price to filter options.
            from_date (str): The start date for option chain data (format: 'YYYY-MM-DD').
            to_date (str): The end date for option chain data (format: 'YYYY-MM-DD').

        Returns:
            list: A list of dictionaries containing expiration date, price, and annualized return.
        """
        if from_date < datetime.now(pytz.timezone("US/Eastern")).strftime('%Y-%m-%d'):
            logger.info("from_date is in the past. Using current date instead.")
            from_date = datetime.now(pytz.timezone("US/Eastern")).strftime('%Y-%m-%d')
            to_date = (datetime.now(pytz.timezone("US/Eastern")) + timedelta(days=8)).strftime('%Y-%m-%d')

        try:
            option_chain = self.client.get_chain(symbol, from_date, to_date, strike_count=50, strike=strike, contract_type=contract_type)
        except BrokerError as e:
            logger.error("Failed to fetch option chain for %s: %s", symbol, e)
            return []

        return self._process_option_chain(option_chain, strike, contract_type)

    def _process_option_chain(self, option_chain, strike: float, contract_type: str):
        """
        Generic method to process an option chain for a given strike price.

        Parameters:
            option_chain: The option chain data.
            strike (float): The strike price to filter options.

        Returns:
            list: A list of processed results.
        """
        results = []
        strike = int(strike)

        def process_option(option, exp_date):
            annualized_return = self._calculate_annualized_return(option.mark, option.strikePrice, option.daysToExpiration)
            return {
                "strike": int(option.strikePrice),
                "expiration_date": exp_date,
                "price": option.mark,
                "annualized_return": annualized_return
            }

        def process_options(exp_date_map):
            for exp_date, strikes in exp_date_map.items():
                for strike_price, options in strikes.items():
                    if float(strike_price) in (strike-1, strike, strike+1):
                        for option in options:
                            if option.mark is None or option.daysToExpiration is None or option.daysToExpiration == 0:
                                logger.debug("Skipping option with invalid data.")
                                continue
                            result = process_option(option, exp_date)
                            if result:
                                results.append(result)

        if contract_type == "PUT":
            process_options(option_chain.putExpDateMap)
        elif contract_type == "CALL":
            process_options(option_chain.callExpDateMap)
        elif contract_type == "ALL":
            process_options(option_chain.putExpDateMap)
            process_options(option_chain.callExpDateMap)
        else:
            logger.warning("Unknown contract type: %s", contract_type)

        return results

    def _calculate_annualized_return(self, price: float, strike: float, days: int) -> float | None:
        """Calculate the annualized return for an option."""
        if days == 0:
            return None
        simple_return = price / strike
        annualized_return = simple_return * (365 / days) * 100
        return round(annualized_return, 2)

    def get_ticker_price(self, symbol):
        """
        Get the current price for a given symbol.

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.

        Returns:
            float: The current price of the asset, or None if not found.
        """
        try:
            stock_quotes = self.client.get_price(symbol)
            return stock_quotes.root.get(symbol).quote.lastPrice
        except BrokerError as e:
            logger.error("Failed to fetch price for %s: %s", symbol, e)
            return None

    def get_price_history(self, symbol, period_type, frequency_type, period):
        """
        Get the price history for a given symbol.

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.

        Returns:
            list: A list of historical prices, or an empty list if not found.
        """
        try:
            price_history = self.client.get_price_history(symbol, period_type=period_type, frequency_type=frequency_type, period=period)
            return price_history.candles
        except BrokerError as e:
            logger.error("Failed to fetch price history for %s: %s", symbol, e)
            return []
