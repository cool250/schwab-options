from datetime import date, datetime, timedelta
from typing import Optional
import logging

from broker.schwab import Client
from broker.schwab.exceptions import BrokerAuthError, BrokerError
from broker.schwab.data.account_data import SecuritiesAccount

logger = logging.getLogger(__name__)


def parse_option_symbol(symbol):
    """Parse an OCC equity option symbol into (ticker, strike_price, expiration_date).

    expiration_date is full 4-digit-year ISO ("2026-09-18"), matching the
    convention used everywhere else in the app (futures options, Transactions'
    expirationDate) — the OCC symbol itself only carries a 2-digit year.
    """
    try:
        strike_price = float(symbol[13:21]) / 1000
        ticker = symbol[:6].strip()
        expiration_date = f"20{symbol[6:8]}-{symbol[8:10]}-{symbol[10:12]}"
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
        except BrokerAuthError:
            # Unlike a transient/API-shaped BrokerError, a dead broker session
            # can't be degraded around — every getter below would just return
            # empty/error-shaped data with a 200, masking the failure (see
            # get_futures_position's identical handling below). Let it
            # propagate so app.py's global handler turns it into a 503.
            raise
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
                    is_long = position.longQuantity > 0
                    quantity = position.longQuantity if is_long else -position.shortQuantity
                    # Schwab's own tax-lot-aware cost basis and unrealized P&L
                    # for this position — computed broker-side, so it can
                    # already reflect things this app's own FIFO reconstruction
                    # doesn't (wash-sale adjustments, a non-FIFO cost-basis
                    # method). Shown alongside our own figures for comparison,
                    # not as a replacement — see averagePrice/trade_price above.
                    broker_cost_basis = position.taxLotAverageLongPrice if is_long else position.taxLotAverageShortPrice
                    broker_pl = position.longOpenProfitLoss if is_long else position.shortOpenProfitLoss
                    stocks.append({
                        "symbol": symbol,
                        "quantity": f"{quantity:,.0f}",
                        "trade_price": f"${position.averagePrice:,.2f}",
                        "broker_cost_basis": f"${broker_cost_basis:,.2f}" if broker_cost_basis is not None else None,
                        "broker_pl": broker_pl,
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

        Deliberately excludes current_price: pricing these requires
        Tastytrade's DXLink feed and can take a few seconds per open root
        symbol, so the frontend fetches that separately via
        get_futures_quotes() once this — the fast part — has already
        rendered, same pattern as get_futures_option_position/_quotes.

        Returns:
            list: [{"symbol", "quantity", "open_price"}, ...]
        """
        from service.transactions import TransactionService  # local: avoid import cost when unused

        # +1 day: convert_to_iso8601 renders end_date as 00:00:00 UTC of that
        # calendar date, which is hours before US markets even open — without
        # this, anything filled "today" (or late evening the day before, US
        # time) falls outside the window until the date rolls over tomorrow.
        end_date = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
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
            })
        return futures

    def get_futures_quotes(self, lookback_days: int = 30) -> dict:
        """Live prices for currently-open outright futures positions, keyed by
        `symbol` (the bare root, e.g. "ES") — split out from get_futures_position
        so that table renders immediately without waiting on Tastytrade's
        DXLink feed, same rationale as get_futures_option_quotes.

        Any symbol whose live price can't be fetched in time is simply
        omitted — this is a display nicety, not something that should ever
        block showing the position.
        """
        positions = self.get_futures_position(lookback_days=lookback_days)
        symbols = [p["symbol"] for p in positions if p.get("symbol")]
        if not symbols:
            return {}

        from broker.tastytrade import TastytradeClient

        try:
            client = TastytradeClient.from_config()
        except ValueError as e:
            logger.error("Tastytrade credentials unavailable for futures quotes: %s", e)
            return {}

        result = {}
        for symbol in symbols:
            try:
                result[symbol] = client.get_live_underlying_price(f"/{symbol}")
            except (ValueError, TimeoutError) as e:
                logger.error("Failed to fetch live price for /%s: %s", symbol, e)
                continue
        return result

    def get_futures_option_position(self, lookback_days: int = 30):
        """Derive currently-open futures-option positions (options on /ES,
        /NQ, etc.) from transaction history — same rationale and the same
        short lookback as get_futures_position(), since Schwab's positions
        endpoint doesn't return these either.

        Deliberately excludes current_price: pricing these requires Tastytrade's
        DXLink feed (Schwab's own quote endpoint flatly rejects futures-option
        symbols — confirmed empirically, 'invalidSymbols') and can add several
        seconds per open expiration, so the frontend fetches that separately
        via get_futures_option_quotes() once this — the fast part — has
        already rendered. A grouped ratio-spread row's own `symbol` is
        synthetic (e.g. "ES 1:2 Ratio (...)") and never matches a real
        contract symbol from that quote lookup, so the row also carries
        `long_leg`/`short_leg` (each with its own real `symbol` and
        quantity) — the frontend uses those to compute a live net Current
        Price the same way trade_price is computed here, rather than a
        single direct lookup.

        Legs that form a ratio spread (buy 1 / sell 2+ at a different
        strike, same underlying/expiration/type, opened together) are
        merged into a single row, with both strikes shown in strike_price
        and a net entry price (short side minus long side, weighted by each
        side's quantity) in trade_price — see
        TransactionService.group_open_ratio_spreads.

        Returns:
            tuple: (puts, calls), each a list of
                {"ticker", "symbol", "strike_price", "expiration_date",
                 "days_to_expiry", "quantity", "trade_price", "total_value",
                 "multiplier"}.
                total_value is trade_price × quantity × contract multiplier
                (same sign convention as the equity-option total_value: short
                positive/credit, long negative/debit) — computed from
                trade_price like the equity version, not the live quote, so
                it renders immediately without waiting on futuresQuotes.
                multiplier is carried through separately so the frontend can
                reprice the position at the live quote and show P&L as
                total_value minus that live-priced value.
        """
        from service.transactions import TransactionService  # local: avoid import cost when unused

        transaction_service = TransactionService()
        try:
            legs = transaction_service.get_open_futures_options(lookback_days=lookback_days)
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to derive futures option positions: %s", e)
            return [], []

        legs = transaction_service.group_open_ratio_spreads(legs)

        puts, calls = [], []
        for leg in legs:
            expiration_date = leg.get("expirationDate")
            days_to_expiry = None
            if expiration_date:
                try:
                    days_to_expiry = (datetime.strptime(expiration_date, "%Y-%m-%d").date() - date.today()).days
                except ValueError:
                    days_to_expiry = None

            is_group = leg.get("strategy") == "RATIO_SPREAD"
            multiplier = TransactionService._get_multiplier(leg.get("underlying_symbol", ""))
            if is_group:
                long_leg, short_leg = leg["long_leg"], leg["short_leg"]
                net = leg.get("net_trade_price", 0)
                strike_price = f"${long_leg['strike_price']:,.0f}/${short_leg['strike_price']:,.0f}"
                trade_price = f"${net:,.2f}" if net >= 0 else f"-${abs(net):,.2f}"
                # Both sides' quantities are already netted into `net`, so the
                # multiplier is applied once here rather than per leg.
                total_value = net * multiplier
            else:
                strike_price = f"${leg.get('strike_price', 0):,.0f}"
                trade_price = f"${leg.get('open_price', leg.get('price', 0)):,.2f}"
                # Same sign convention as the equity-option total_value above:
                # short (negative amount) shows a positive credit received,
                # long (positive amount) shows a negative debit paid.
                total_value = leg.get("open_price", leg.get("price", 0)) * -leg.get("amount", 0) * multiplier

            option_details = {
                "ticker": leg.get("underlying_symbol"),
                "symbol": leg.get("symbol"),
                "strike_price": strike_price,
                "expiration_date": expiration_date,
                "days_to_expiry": days_to_expiry,
                "quantity": leg.get("ratio") if is_group else f"{leg.get('amount', 0):,.0f}",
                "trade_price": trade_price,
                "total_value": total_value,
                # Carried through (rather than baked only into total_value) so
                # the frontend can price the *same* position at the live quote
                # once futuresQuotes loads, and derive P&L as the difference —
                # see futuresPnLColumn() in Positions.jsx.
                "multiplier": multiplier,
            }
            if is_group:
                # Carried through so the frontend can compute a live net
                # Current Price the same way (each real leg's own symbol,
                # looked up in the separately-fetched quotes dict, weighted
                # by that leg's quantity) — the group's own `symbol` above
                # is synthetic and won't match a real quote.
                option_details["long_leg"] = leg["long_leg"]
                option_details["short_leg"] = leg["short_leg"]
            (puts if leg.get("option_type") == "PUT" else calls).append(option_details)
        return puts, calls

    def get_futures_option_quotes(self, lookback_days: int = 30) -> dict:
        """Live bid prices for currently-open futures-option positions, keyed
        by the same `symbol` individual (ungrouped) legs carry in
        get_futures_option_position() — split out from that method so the
        position table itself can render immediately without waiting on
        Tastytrade's DXLink feed. Deliberately fetches its own flat, ungrouped
        legs rather than reusing get_futures_option_position()'s (which
        merges ratio-spread legs into synthetic multi-leg rows) — each real
        contract needs its own symbol to look up a quote for.
        """
        from service.transactions import TransactionService  # local: avoid import cost when unused

        try:
            legs = TransactionService().get_open_futures_options(lookback_days=lookback_days)
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to derive futures option positions for quoting: %s", e)
            return {}

        return self._get_futures_option_quotes(legs)

    @staticmethod
    def _get_futures_option_quotes(legs: list) -> dict:
        """Fetch live bid prices for a set of derived futures-option legs via
        Tastytrade's DXLink feed, grouped by (root symbol, expiration) so each
        expiration's chain is only fetched once regardless of how many
        strikes/types are open on it.

        Returns {symbol: bid_price}. Any leg whose chain fetch fails, or whose
        contract/quote can't be found, is simply omitted — this is a display
        nicety, not something that should ever block showing the position.
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
        symbol_by_streamer_symbol = {}

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
                symbol_by_streamer_symbol[streamer_symbol] = leg.get("symbol")

        if not matched_contracts:
            return {}

        try:
            quotes = client.get_chain_quotes(matched_contracts)
        except TastytradeAPIError as e:
            logger.error("Failed to fetch futures-option quotes: %s", e)
            return {}

        result = {}
        for streamer_symbol, symbol in symbol_by_streamer_symbol.items():
            quote = quotes.get(streamer_symbol)
            if quote and quote.get("bid") is not None and symbol:
                result[symbol] = quote["bid"]
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
                        exp = datetime.strptime(expiration_date, "%Y-%m-%d").date()
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
                        # Cost basis for now — get_current_price() (called by
                        # every caller of this method) turns this into
                        # unrealized P&L once the live quote is known.
                        "total_value": (position.averagePrice or 0) * -quantity * 100
                    }
                    option_positions_details.append(option_details)
        return option_positions_details

    def get_current_price(self, tickers):
        """Fetch the current price for the given options.

        For options (identified by the presence of `total_value`, which
        stock entries don't carry), total_value is repurposed here from a
        trade-price cost basis into unrealized P&L — cost basis minus that
        same position priced at the live quote, same sign convention as
        before: short/credit positive, long/debit negative.
        """
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
            if "total_value" in ticker:
                quantity = float(str(ticker.get("quantity", 0)).replace(",", "") or 0)
                current_value = current_price * -quantity * 100
                ticker["total_value"] = ticker["total_value"] - current_value

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
