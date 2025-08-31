from broker.accounts import AccountsTrading
from broker.market_data import MarketData


class PositionService:

    def fetch_option_positions_details(self, accounts_trading):
        """
        Fetch option positions details directly using AccountsTrading.
        """
        puts = self.get_current_price(accounts_trading.get_puts())
        calls = self.get_current_price(accounts_trading.get_calls())
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
        # Initialize the AccountsTrading class
        accounts_trading = AccountsTrading()
        # Fetch the securities account
        securities_account = accounts_trading.get_positions()
        option_positions = self.fetch_option_positions_details(accounts_trading)
        total_exposure = self.fetch_total_exposure(accounts_trading)
        account_balances = self.get_balances(accounts_trading)

        return option_positions, total_exposure, account_balances
    
    def fetch_total_exposure(self, accounts_trading):
        """
        Fetch the total exposure for short PUT options directly using AccountsTrading.
        """
        return accounts_trading.calculate_total_exposure_for_short_puts()

    def get_balances(self, accounts_trading):
        """
        Fetch account balances directly using AccountsTrading.
        """
        return accounts_trading.get_balances()
    


