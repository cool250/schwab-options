from datetime import date, datetime, timedelta
from typing import Optional
import logging

from broker.schwab import Client
from broker.schwab.exceptions import BrokerAuthError, BrokerError
from broker.schwab.data.account_data import SecuritiesAccount

logger = logging.getLogger(__name__)


def parse_option_symbol(symbol):
    """Parse an OCC equity option symbol into (ticker, strike_price, expiration_date)."""
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
        self.client = Client()
        self.position: Optional[SecuritiesAccount] = None
        self._initialize()

    def _initialize(self):
        try:
            self.position = self.client.fetch_positions()
        except BrokerError as e:
            logger.error("Failed to fetch positions: %s", e)
            self.position = None

    # --- Top-level aggregator ---

    def populate_positions(self):
        """Populate option positions with current prices, total exposure, and account balances.

        Deliberately excludes futures/futures-options — those are derived from
        transaction history (see get_futures_position/get_futures_option_position)
        and the latter's Tastytrade quote lookups add several seconds of
        latency, so the frontend only fetches them on demand when the user
        actually opens the Futures tab, not on every equity-tab page load.
        """
        option_positions = self.get_option_position()
        account_balances = self.get_balances()
        stocks = self.get_stock_position()

        return option_positions, account_balances, stocks

    # --- Public getters ---

    def get_positions(self):
        return self.position

    def get_balances(self) -> dict:
        """Fetch and log the account balances."""
        if self.position is None:
            logger.warning("Position is not initialized.")
            return {"error": "Position is not initialized."}
        securities_account: SecuritiesAccount = self.position
        current = securities_account.currentBalances
        if current is None:
            logger.warning("Current balances are not available.")
            return {"error": "Current balances are not available."}

        margin = current.marginBalance
        cash = current.cashBalance
        balances = {
            "mutualFundValue": current.mutualFundValue,
            "account": current.liquidationValue,
            "cash_balance": cash if (margin is None or margin >= 0) else margin,
        }
        logger.debug(f"Account Balances: {balances}")
        return balances

    def get_stock_position(self):
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
            if position.instrument and position.instrument.assetType in ("EQUITY", "COLLECTIVE_INVESTMENT"):
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

    def get_futures_position(self, lookback_days: int = 30):
        """Derive currently-open futures positions from transaction history.

        Schwab's positions endpoint doesn't return futures contracts at all, so
        this reconstructs them by FIFO-matching transaction history (see
        TransactionService.get_equity_transactions) and netting whatever's left
        open per root symbol (e.g. 'ES', 'NQ').

        This is a best-effort reconstruction, not authoritative like the real
        positions endpoint, and only sees `lookback_days` back — kept short
        (30 days) by design rather than Schwab's ~1-year request cap, since a
        wider window risks surfacing a leg that actually closed outside it, or
        hit some matching edge case, as a stale "still open" position.
        """
        from service.transactions import TransactionService  # local: avoid import cost when unused

        end_date = date.today().strftime("%Y-%m-%d")
        start_date = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        try:
            trades = TransactionService().get_equity_transactions(
                "", start_date, end_date, asset_type="FUTURE", realized_gains_only=False
            )
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to derive futures positions: %s", e)
            return []

        by_symbol: dict[str, dict] = {}
        for trade in trades:
            if trade.get("closed"):
                continue
            entry = by_symbol.setdefault(trade["symbol"], {"quantity": 0.0, "cost": 0.0, "weighted_price": 0.0})
            entry["quantity"] += trade["quantity"]
            entry["cost"] += trade["total_amount"]
            entry["weighted_price"] += trade["open_price"] * abs(trade["quantity"])

        futures = []
        for symbol, entry in by_symbol.items():
            if abs(entry["quantity"]) < 1e-9:
                continue
            avg_price = entry["weighted_price"] / abs(entry["quantity"])
            futures.append({
                "symbol": symbol,
                "quantity": f"{entry['quantity']:,.0f}",
                "open_price": f"${avg_price:,.2f}",
                "cost_basis": f"${entry['cost']:,.2f}",
            })
        return futures

    def get_futures_option_position(self, lookback_days: int = 30):
        """Derive currently-open futures-option positions (options on /ES,
        /NQ, etc.) from transaction history — same rationale and the same
        short lookback as get_futures_position(), since Schwab's positions
        endpoint doesn't return these either.

        Also attaches a live current_price via Tastytrade's DXLink feed:
        Schwab's own quote endpoint flatly rejects futures-option symbols
        (confirmed empirically — 'invalidSymbols'), so there's no Schwab-only
        way to price these.

        Returns:
            tuple: (puts, calls), each a list of
                {"ticker", "symbol", "strike_price", "expiration_date",
                 "days_to_expiry", "quantity", "trade_price", "current_price"}.
        """
        from service.transactions import TransactionService  # local: avoid import cost when unused

        try:
            legs = TransactionService().get_open_futures_options(lookback_days=lookback_days)
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to derive futures option positions: %s", e)
            return [], []

        quotes_by_leg = self._get_futures_option_quotes(legs)

        puts, calls = [], []
        for leg in legs:
            expiration_date = leg.get("expirationDate")
            days_to_expiry = None
            if expiration_date:
                try:
                    days_to_expiry = (datetime.strptime(expiration_date, "%Y-%m-%d").date() - date.today()).days
                except ValueError:
                    days_to_expiry = None

            quote_key = (leg.get("underlying_symbol"), expiration_date, leg.get("strike_price"), leg.get("option_type"))
            current_price = quotes_by_leg.get(quote_key)

            option_details = {
                "ticker": leg.get("underlying_symbol"),
                "symbol": leg.get("symbol"),
                "strike_price": f"${leg.get('strike_price', 0):,.0f}",
                "expiration_date": expiration_date,
                "days_to_expiry": days_to_expiry,
                "quantity": f"{leg.get('amount', 0):,.0f}",
                "trade_price": f"${leg.get('open_price', leg.get('price', 0)):,.2f}",
                "current_price": f"${current_price:,.2f}" if current_price is not None else None,
            }
            (puts if leg.get("option_type") == "PUT" else calls).append(option_details)
        return puts, calls

    @staticmethod
    def _get_futures_option_quotes(legs: list) -> dict:
        """Fetch live mid-prices (bid/ask average) for a set of derived
        futures-option legs via Tastytrade's DXLink feed, grouped by
        (root symbol, expiration) so each expiration's chain is only fetched
        once regardless of how many strikes/types are open on it.

        Returns {(ticker, expiration_date, strike_price, option_type): mid_price}.
        Any leg whose chain fetch fails, or whose contract/quote can't be
        found, is simply omitted — this is a display nicety, not something
        that should ever block showing the position itself.
        """
        if not legs:
            return {}

        from broker.tastytrade import TastytradeAPIError, TastytradeClient

        try:
            client = TastytradeClient.from_config()
        except ValueError as e:
            logger.error("Tastytrade credentials unavailable for futures-option quotes: %s", e)
            return {}

        by_group: dict[tuple, list] = {}
        for leg in legs:
            key = (leg.get("underlying_symbol"), leg.get("expirationDate"))
            by_group.setdefault(key, []).append(leg)

        option_type_code = {"PUT": "P", "CALL": "C"}
        matched_contracts = []
        quote_key_by_streamer_symbol = {}

        for (root, expiration_date), group_legs in by_group.items():
            if not root or not expiration_date:
                continue
            try:
                contracts = client.get_future_option_chain(f"/{root}", expiration_date=expiration_date)
            except (TastytradeAPIError, ValueError) as e:
                logger.error("Failed to fetch futures-option chain for /%s %s: %s", root, expiration_date, e)
                continue

            by_strike_type = {}
            for contract in contracts:
                try:
                    by_strike_type[(float(contract["strike-price"]), contract["option-type"])] = contract
                except (KeyError, TypeError, ValueError):
                    continue

            for leg in group_legs:
                strike = leg.get("strike_price")
                code = option_type_code.get(leg.get("option_type"))
                contract = by_strike_type.get((strike, code)) if strike is not None and code else None
                streamer_symbol = contract.get("streamer-symbol") if contract else None
                if not streamer_symbol:
                    continue
                matched_contracts.append(contract)
                quote_key_by_streamer_symbol[streamer_symbol] = (root, expiration_date, strike, leg.get("option_type"))

        if not matched_contracts:
            return {}

        try:
            quotes = client.get_chain_quotes(matched_contracts)
        except TastytradeAPIError as e:
            logger.error("Failed to fetch futures-option quotes: %s", e)
            return {}

        result = {}
        for streamer_symbol, quote_key in quote_key_by_streamer_symbol.items():
            quote = quotes.get(streamer_symbol)
            if quote and quote.get("bid") is not None and quote.get("ask") is not None:
                result[quote_key] = (quote["bid"] + quote["ask"]) / 2
        return result

    def get_option_position(self):
        """Fetch option positions details including current prices."""
        puts = self._get_positions_with_prices("P")
        calls = self._get_positions_with_prices("C")
        return puts, calls

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

    # --- Private helpers ---

    def _get_positions_with_prices(self, option_type):
        """Fetch options of a specific type and populate their current prices."""
        options = self.get_option_details(option_type)
        options_with_prices = self.get_current_price(options)
        return options_with_prices

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
                else:
                    continue

                if ticker:
                    if position.longQuantity and position.longQuantity > 0:
                        quantity = position.longQuantity
                    elif position.shortQuantity and position.shortQuantity > 0:
                        quantity = -position.shortQuantity
                    else:
                        logger.warning(f"Position {symbol} has no long or short quantity, skipping.")
                        continue
                    exposure = PositionService._calculate_exposure(position, strike_price)
                    if expiration_date:
                        exp = datetime.strptime(expiration_date, "%y-%m-%d").date()
                        days_to_expiry = (exp - date.today()).days
                    else:
                        days_to_expiry = None
                    option_details = {
                        "ticker": ticker,
                        "symbol": symbol,
                        "strike_price": f"${strike_price:,.0f}",
                        "expiration_date": expiration_date,
                        "days_to_expiry": days_to_expiry,
                        "quantity": f"{quantity:,.0f}",
                        "exposure": exposure,
                        "trade_price": f"${position.averagePrice:,.2f}",
                        "total_value": (position.averagePrice or 0) * -quantity * 100
                    }
                    option_positions_details.append(option_details)
        return option_positions_details

    def get_current_price(self, tickers):
        """Fetch the current price for the given options."""
        ticker_list = [ticker.get("symbol") for ticker in tickers if ticker.get("symbol")]

        if not ticker_list:
            return tickers

        try:
            quotes = self.client.get_price(",".join(ticker_list))
            quote_data = {
                symbol: asset.quote.mark
                for symbol, asset in getattr(quotes, "root", {}).items()
                if asset.quote and asset.quote.mark is not None
            }
        except BrokerError as e:
            logger.error("Failed to fetch current prices: %s", e)
            quote_data = {}

        for ticker in tickers:
            current_price = quote_data.get(ticker.get("symbol"), 0)
            ticker["current_price"] = f"${current_price:,.3f}"

        return tickers

    @classmethod
    def _calculate_exposure(cls, position, strike_price):
        """Calculate exposure for PUT options."""
        exposure = 0

        if position.shortQuantity and position.shortQuantity > 0:
            exposure += strike_price * position.shortQuantity * 100
        if position.longQuantity and position.longQuantity > 0:
            exposure -= strike_price * position.longQuantity * 100

        return exposure
