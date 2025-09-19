from typing import Optional
from loguru import logger
from broker import Accounts, MarketData
from model.account_models import SecuritiesAccount

def parse_option_symbol(symbol):
    """Parse the option symbol to extract ticker, strike price, and expiration date."""
    try:
        strike_price = float(symbol[13:21]) / 1000
        ticker = symbol[:6].strip()
        expiration_date = f"{symbol[6:8]}-{symbol[8:10]}-{symbol[10:12]}"
        return ticker, strike_price, expiration_date
    except ValueError as e:
        logger.error(f"Error parsing option symbol {symbol}: {e}")
        return None, None, None

class PositionService:

    def __init__(self):
        self.market_data = MarketData()
        self.position: Optional[SecuritiesAccount] = None
        self._initialize()
    
    def _initialize(self):
        self.position = Accounts().fetch_positions()
    
    def get_positions(self):
        return self.position

    def get_option_positions_details(self):
        """Fetch option positions details including current prices."""
        puts = self._get_options_with_prices("P")
        calls = self._get_options_with_prices("C")
        return puts, calls

    def _get_options_with_prices(self, option_type):
        """Fetch options of a specific type and populate their current prices."""
        options = self.get_option_details(option_type)
        return self.get_current_price(options)

    def get_current_price(self, tickers):
        """Fetch the current price for the given options."""
        ticker_list = [ticker.get("symbol") for ticker in tickers if ticker.get("symbol")]

        if not ticker_list:
            return tickers

        quotes = self.market_data.get_price(", ".join(ticker_list))
        quote_data = {
            symbol: asset.quote.mark
            for symbol, asset in getattr(quotes, "root", {}).items()
            if asset.quote and asset.quote.mark is not None
        }

        for ticker in tickers:
            current_price = quote_data.get(ticker.get("symbol"), 0)
            ticker["current_price"] = f"${current_price:,.3f}"

        return tickers

    def populate_positions(self):
        """Populate option positions with current prices, total exposure, and account balances."""
        option_positions = self.get_option_positions_details()
        total_exposure = self.get_total_exposure()
        account_balances = self.get_balances()
        stocks = self.get_stocks()

        return option_positions, total_exposure, account_balances, stocks


    def get_stocks(self):
        """Fetch and log the account stocks."""
        if self.position is None:
            logger.warning("Position is not initialized.")
            return []
        securities_account: SecuritiesAccount = self.position

        stocks = []

        if not securities_account.positions:
            logger.warning("No positions found in the securities account.")
            return []

        for position in securities_account.positions:
            if position.instrument and position.instrument.assetType in ("EQUITY","COLLECTIVE_INVESTMENT"):
                symbol = position.instrument.symbol
                if symbol:
                    quantity = position.longQuantity if position.longQuantity > 0 else -position.shortQuantity
                    stocks.append({
                        "symbol": symbol,
                        "quantity": f"{quantity:,.0f}",
                        "trade_price": f"${position.averagePrice:,.2f}",
                    })
        stocks = self.get_current_price(stocks)
        return stocks

    def get_balances(self) -> dict:
        """Fetch and log the account balances."""
        if self.position is None:
            logger.warning("Position is not initialized.")
            return {"error": "Position is not initialized."}
        securities_account: SecuritiesAccount = self.position

        balances = {
            "margin": securities_account.currentBalances.cashBalance,
            "mutualFundValue": securities_account.currentBalances.mutualFundValue,
            "account": securities_account.currentBalances.liquidationValue
        }
        logger.debug(f"Account Balances: {balances}")
        return balances

    def get_option_details(self, option_type: str):
        """Extract details for each option position based on the option type."""
        if self.position is None:
            logger.warning("Position is not initialized.")
            return []
        securities_account: SecuritiesAccount = self.position
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
                        if position.longQuantity and position.longQuantity > 0:
                            quantity = position.longQuantity
                        elif position.shortQuantity and position.shortQuantity > 0:
                            quantity = -position.shortQuantity
                        exposure = self._calculate_exposure(option_type, position, strike_price)
                        option_details = {
                            "ticker": ticker,
                            "symbol": symbol,
                            "strike_price": f"${strike_price:,.0f}",
                            "expiration_date": expiration_date,
                            "quantity": f"{quantity:,.0f}",
                            "exposure": exposure,
                            "trade_price": f"${position.averagePrice:,.2f}",
                        }
                        option_positions_details.append(option_details)
        return option_positions_details

    def _calculate_exposure(self, option_type, position, strike_price):
        """Calculate exposure for PUT options."""
        exposure = 0
      
        if position.shortQuantity and position.shortQuantity > 0:
            exposure += strike_price * position.shortQuantity * 100
        if position.longQuantity and position.longQuantity > 0:
            exposure -= strike_price * position.longQuantity * 100
       
        return exposure

    def get_total_exposure(self):
        """Calculate and log the total exposure for short PUT option positions."""
        puts = self.get_option_details("P")
        exposure_by_symbol = {}

        for put in puts:
            ticker = put["ticker"]
            exposure = put.get("exposure", 0)
            exposure_by_symbol[ticker] = exposure_by_symbol.get(ticker, 0) + exposure

        logger.debug(f"Total Exposure: {exposure_by_symbol}")
        return exposure_by_symbol


