from datetime import datetime

from loguru import logger
from broker.market_data import MarketData

class MarketService:
    def __init__(self):
        self.market_data = MarketData()

    def highest_return_puts(self, symbol: str, strike: float, from_date: str, to_date: str):
        """
        Finds the put option with the highest annualized return for a given symbol and strike price.

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.
            strike (float): The strike price to filter options.
            from_date (str): The start date for option chain data (format: 'YYYY-MM-DD').
            to_date (str): The end date for option chain data (format: 'YYYY-MM-DD').

        Returns:
            tuple: (max_return (float), best_expiration_date (str), best_price (float))
                max_return: The highest annualized return found.
                best_expiration_date: The expiration date of the best option.
                best_price: The price of the best option.
                Returns None if no suitable option is found.
        """
        option_chain = self.market_data.get_chain(symbol, from_date, to_date, strike_count=20, contract_type="PUT")

        def process_option(option, exp_date):
            annualized_return = self._calculate_annualized_return(option.mark, strike, option.daysToExpiration)
            return {
                "annualized_return": annualized_return,
                "expiration_date": exp_date,
                "price": option.mark
            }

        results = self._process_option_chain(option_chain, strike, process_option)
        if not results:
            return None

        best_option = max(results, key=lambda x: x["annualized_return"], default=None)
        if not best_option:
            return None

        return best_option["annualized_return"], best_option["expiration_date"], best_option["price"]

    def get_all_expiration_dates(self, symbol: str, strike: float, from_date: str, to_date: str):
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
        option_chain = self.market_data.get_chain(symbol, from_date, to_date, strike_count=20, contract_type="PUT")

        def process_option(option, exp_date):
            annualized_return = self._calculate_annualized_return(option.mark, strike, option.daysToExpiration)
            return {
                "expiration_date": exp_date,
                "price": option.mark,
                "annualized_return": annualized_return
            }

        return self._process_option_chain(option_chain, strike, process_option)

    def _process_option_chain(self, option_chain, strike: float, process_function):
        """
        Generic method to process an option chain for a given strike price.

        Parameters:
            option_chain: The option chain data.
            strike (float): The strike price to filter options.
            process_function (callable): A function to process each valid option.

        Returns:
            list: A list of processed results.
        """
        if not option_chain or not option_chain.putExpDateMap:
            logger.warning("No option chain data found or putExpDateMap is empty.")
            return []

        results = []

        for exp_date, strikes in option_chain.putExpDateMap.items():
            for strike_price, options in strikes.items():
                if float(strike_price) == strike:
                    for option in options:
                        if option.mark is None or option.daysToExpiration is None:
                            logger.debug("Skipping option with invalid data.")
                            continue

                        result = process_function(option, exp_date)
                        if result:
                            results.append(result)

        return results

    def _calculate_annualized_return(self, price: float, strike: float, days: int) -> float:
        """Calculate the annualized return for an option."""
        if days == 0:
            return float('-inf')
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
        stock_quotes = self.market_data.get_price(symbol)
        if stock_quotes:
            return stock_quotes.root.get(symbol).quote.lastPrice
        return None
