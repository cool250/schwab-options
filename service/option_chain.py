from datetime import datetime

from loguru import logger
from broker.market_data import MarketData

class OptionChainService:
    def __init__(self):
        self.market_data = MarketData()

    def highest_return_puts(self, symbol: str, strike: float, from_date: str, to_date: str, use_mid_price: bool = True):
        """
        Finds the put option with the highest annualized return for a given symbol and strike price.

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.
            strike (float): The strike price to filter options.
            from_date (str): The start date for option chain data (format: 'YYYY-MM-DD').
            to_date (str): The end date for option chain data (format: 'YYYY-MM-DD').
            use_mid_price (bool, optional): If True, use the mid price (average of bid and ask); otherwise, use the mark price if available. Defaults to True.

        Returns:
            tuple: (max_return (float), best_expiration_date (str), best_price (float))
                max_return: The highest annualized return found.
                best_expiration_date: The expiration date of the best option.
                best_price: The price of the best option.
                Returns None if no suitable option is found.
        """
        option_chain = self.market_data.get_chain(symbol, from_date, to_date, strike_count=25, contract_type="PUT")
        if not option_chain or not option_chain.putExpDateMap:
            return None

        max_return = float('-inf')
        best_expiration_date = None
        best_price = float('-inf')

        now = datetime.now()

        logger.info(f"Total expiration dates in putExpDateMap: {len(option_chain.putExpDateMap)}")
        for exp_date, strikes in option_chain.putExpDateMap.items():
            logger.info(f"Total strikes for expiration date {exp_date}: {len(strikes)}")
            for strike_price, options in strikes.items():
                if float(strike_price) == strike:
                    for option in options:
                        price = (option.bid + option.ask) / 2 if use_mid_price else option.mark
                        days = option.daysToExpiration
                        if days == 0:
                            continue
                        simple_return = price / strike  # Calculate return as a percentage
                        annualized_return = simple_return * (365 / days) * 100  # Annualize the return
                        annualized_return = round(annualized_return, 2)  # Format as percentage with 2 decimal places
                        if annualized_return > max_return:
                            max_return = annualized_return
                            best_expiration_date = exp_date
                            best_price = price

        return max_return, best_expiration_date, best_price

