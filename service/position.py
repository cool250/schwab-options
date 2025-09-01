from loguru import logger
from broker.accounts import AccountsTrading
from broker.market_data import MarketData
from model.account_models import SecuritiesAccount


class PositionService:

    def __init__(self):
        self.market_data = MarketData()
        self.accounts_trading = AccountsTrading()

    def fetch_option_positions_details(self):
        """
        Fetch option positions details directly using AccountsTrading.
        """
        puts = self.get_current_price(self.get_puts())
        calls = self.get_current_price(self.get_calls())
        return puts, calls

    def get_current_price(self, options):
        """
        Fetch the price position for the given options.
        """
        price_positions = [option.get("symbol") for option in options if option.get("symbol")]

        if not price_positions: # should ideally not be empty
            return options

        market_data = MarketData() 
        # Pass all symbols to market data as comma separated values
        quotes = market_data.get_price(", ".join(price_positions))
        quote_data = {}
        if quotes and hasattr(quotes, "root"):
            quote_data = {
                symbol: asset.quote.closePrice
                for symbol, asset in quotes.root.items()
                if asset.quote and asset.quote.closePrice is not None
            }

        for option in options:
            current_price = quote_data.get(option.get("symbol"), 0)
            option["current_price"] = f"${current_price:,.2f}"

        return options

    def populate_positions(self):
        """
        Populate option positions with current prices.
        """
        accounts_trading = self.accounts_trading

        # Fetch the securities account
        accounts_trading.fetch_positions()
        option_positions = self.fetch_option_positions_details()
        total_exposure = self.fetch_total_exposure()
        account_balances = self.get_balances()

        return option_positions, total_exposure, account_balances

    def get_balances(self):
        """
        Fetch and log the account balances.
        """
        securities_account: SecuritiesAccount = self.accounts_trading.get_account()

        balances = {
            "margin": securities_account.initialBalances.margin if securities_account.initialBalances else None
        }
        logger.debug(f"Account Balances: {balances}")
        return balances
    
    def get_option_details(self, option_type: str):
        """
        Extract details for each option position including ticker, strike price, exposure, and expiration date.

        Args:
            option_type (str): The type of option to filter ('P' for PUT, 'C' for CALL).
            option_type (str): The type of option to filter ('P' for PUT, 'C' for CALL).

        Returns:
            list: A list of dictionaries with details for each option position.
        """
        securities_account: SecuritiesAccount = self.accounts_trading.get_account()

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
        if not securities_account.positions:
            logger.warning("No positions found in the securities account.")
            return []

        for position in securities_account.positions:
            if position.instrument and position.instrument.assetType == "OPTION":
                symbol = position.instrument.symbol
                if symbol and len(symbol) > 15 and symbol[-9] == option_type:
                    ticker, strike_price, expiration_date = parse_option_symbol(symbol)
                    if ticker:
                        quantity = position.longQuantity or position.shortQuantity
                        exposure = 0
                        option_details = {
                            "ticker": ticker,
                            "symbol": symbol,
                            "strike_price": f"${strike_price:,.2f}",
                            "expiration_date": expiration_date,
                            "quantity": quantity,
                            "trade_price": f"${position.averagePrice:,.2f}" if position.averagePrice else None
                        }
                        if option_type == "P":  # Calculate exposure only for PUT options
                            if position.shortQuantity and position.shortQuantity > 0:
                                # Calculate exposure for short options
                                exposure += strike_price * position.shortQuantity * 100  # Assuming 100 shares per option contract
                            if position.longQuantity and position.longQuantity > 0:
                                # Calculate exposure for long options
                                exposure -= strike_price * position.longQuantity * 100  # Assuming 100 shares per option contract
                            option_details["exposure"] = exposure

                        option_positions_details.append(option_details)
        return option_positions_details

    def get_puts(self):
        """
        Extract details for PUT option positions.

        Args:
            securities_account (SecuritiesAccount): The SecuritiesAccount object containing positions.

        Returns:
            list: A list of dictionaries with details for each PUT option position.
        """
        return self.get_option_details(option_type="P")

    def get_calls(self):
        """
        Extract details for CALL option positions.

        Args:
            securities_account (SecuritiesAccount): The SecuritiesAccount object containing positions.

        Returns:
            list: A list of dictionaries with details for each CALL option position.
        """
        return self.get_option_details(option_type="C")

    def fetch_total_exposure(self):
        """
        Calculate and log the total exposure for short PUT option positions at the symbol level, 
        considering long PUT options to reduce the exposure.

        Args:
            securities_account (SecuritiesAccount): The SecuritiesAccount object containing positions.
        """
        puts = self.get_puts()
        exposure_by_symbol = {}

        for put in puts:
            ticker = put["ticker"]
            exposure = put.get("exposure", 0)
            exposure_by_symbol[ticker] = exposure_by_symbol.get(ticker, 0) + exposure

        logger.debug(f"Total Exposure: {exposure_by_symbol}")
        return exposure_by_symbol


