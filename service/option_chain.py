from datetime import datetime

from loguru import logger
from broker.market_data import MarketData

class OptionChainService:
    def __init__(self):
        self.market_data = MarketData()

    def highest_return_puts(self, symbol: str, strike: float, from_date: str, to_date: str, use_mid_price: bool = True):
        option_chain = self.market_data.get_chain(symbol, from_date, to_date)
        if not option_chain or not option_chain.putExpDateMap:
            return None

        max_return = float('-inf')
        best_expiration_date = None
        price = float('-inf')

        now = datetime.now()

        logger.info(f"Total expiration dates in putExpDateMap: {len(option_chain.putExpDateMap)}")
        for exp_date, strikes in option_chain.putExpDateMap.items():
            logger.info(f"Total strikes for expiration date {exp_date}: {len(strikes)}")
            for strike_price, options in strikes.items():
                if float(strike_price) == strike:
                    for option in options:
                        price = (option.bid + option.ask) / 2 if use_mid_price else option.mark
                        days = option.daysToExpiration
                        simple_return = price / strike * 100  # Calculate return as a percentage
                        annualized_return = (simple_return * (365 / days)) if days > 0 else 0  # Annualize the return
                        annualized_return = round(annualized_return, 2)  # Format as percentage with 2 decimal places
                        if annualized_return > max_return:
                            max_return = annualized_return
                            best_expiration_date = exp_date
                            logger.info(f"Price: {price} Date: {exp_date}")
                        
        return max_return, best_expiration_date, price

