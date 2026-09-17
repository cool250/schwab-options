from datetime import date, datetime
from typing import Optional
import logging

from broker.schwab.exceptions import BrokerAuthError, BrokerError
from broker.tastytrade import TastytradeAPIError
from service.account_data_providers import (
    PositionProvider,
    get_contract_multiplier,
    get_position_provider,
    parse_tastytrade_future_option_symbol,
    resolve_tastytrade_account_number,
)

logger = logging.getLogger(__name__)


class PositionService:

    def __init__(self, provider: Optional[PositionProvider] = None):
        self.provider = provider or get_position_provider()
        self._snapshot: Optional[dict] = None
        self._init_error: Optional[Exception] = None
        self._initialize()

    def _initialize(self):
        try:
            self._snapshot = self.provider.get_account_snapshot()
        except BrokerAuthError:
            # Unlike a transient/API-shaped BrokerError, a dead broker session
            # can't be degraded around — every getter below would just return
            # empty/error-shaped data with a 200, masking the failure (see
            # get_futures_position's identical handling below). Let it
            # propagate so app.py's global handler turns it into a 503.
            raise
        except (BrokerError, TastytradeAPIError) as e:
            # TastytradeAPIError alongside BrokerError: when
            # ACCOUNT_BROKER_PROVIDER=tastytrade, self.provider is a
            # TastytradePositionProvider and raises Tastytrade's own
            # exception type instead — it doesn't distinguish auth vs other
            # failures the way Schwab's BrokerAuthError/BrokerError split
            # does (see api/app.py's tastytrade_error_handler), so every
            # TastytradeAPIError here degrades the same way a generic
            # BrokerError would rather than propagating as a 503.
            logger.error("Failed to fetch positions: %s", e)
            self._snapshot = None
            self._init_error = e

    def _require_snapshot(self) -> dict:
        """Raise the error that broke initial position fetch instead of
        letting a caller silently treat "not fetched" the same as "genuinely
        no positions" — a broker outage should surface to the user as a
        system error (app.py's BrokerError handler -> 502), not as an empty
        portfolio."""
        if self._snapshot is None:
            raise self._init_error or BrokerError("Position data is unavailable.")
        return self._snapshot

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
        snapshot = self._require_snapshot()
        current = snapshot["balances"]
        if current is None:
            logger.warning("Current balances are not available.")
            return {"error": "Current balances are not available."}

        margin = current["margin_balance"]
        cash = current["cash_balance"]
        balances = {
            "mutualFundValue": current["mutual_fund_value"],
            "account": current["liquidation_value"],
            "cash_balance": cash if (margin is None or margin >= 0) else margin,
        }
        logger.debug(f"Account Balances: {balances}")
        return balances

    def get_stock_position(self):
        """Fetch and log the account stocks."""
        snapshot = self._require_snapshot()

        stocks = []
        for position in snapshot["positions"]:
            if position["asset_type"] not in ("EQUITY", "COLLECTIVE_INVESTMENT"):
                continue
            is_long = position["long_quantity"] > 0
            quantity = position["long_quantity"] if is_long else -position["short_quantity"]
            # The broker's own tax-lot-aware cost basis and unrealized P&L
            # for this position — computed broker-side, so it can already
            # reflect things this app's own FIFO reconstruction doesn't
            # (wash-sale adjustments, a non-FIFO cost-basis method). Shown
            # alongside our own figures for comparison, not as a replacement
            # — see average_price/trade_price above.
            broker_cost_basis = position["tax_lot_long_price"] if is_long else position["tax_lot_short_price"]
            broker_pl = position["long_open_pl"] if is_long else position["short_open_pl"]
            stocks.append({
                "symbol": position["symbol"],
                "quantity": f"{quantity:,.0f}",
                "trade_price": f"${position['average_price']:,.2f}",
                "broker_cost_basis": f"${broker_cost_basis:,.2f}" if broker_cost_basis is not None else None,
                "broker_pl": broker_pl,
            })
        stocks = self.get_current_price(stocks)
        return stocks

    def get_futures_position(self, lookback_days: int = 30):
        """Currently-open outright futures positions (e.g. root 'ES', 'NQ'),
        sourced directly from Tastytrade's own positions endpoint.

        Unlike Schwab's positions endpoint (which omits futures entirely —
        the reason this used to reconstruct them from transaction history via
        FIFO-matching), Tastytrade's /accounts/{id}/positions returns "Future"
        instrument-type entries directly: authoritative, not a best-effort
        reconstruction, and not bounded to a lookback window. Fetched from
        Tastytrade regardless of which broker ACCOUNT_BROKER_PROVIDER
        currently has equity/option positions pointed at — futures quotes
        below already worked this way.

        lookback_days is accepted but unused now — kept for signature
        compatibility with existing callers (get_futures_quotes, the copilot
        tool) from when this reconstructed from a bounded transaction window;
        the positions endpoint always reflects whatever's open right now.

        Deliberately excludes current_price: pricing these requires
        Tastytrade's DXLink feed and can take a few seconds per open root
        symbol, so the frontend fetches that separately via
        get_futures_quotes() once this — the fast part — has already
        rendered, same pattern as get_futures_option_position/_quotes.

        Returns:
            list: [{"symbol", "quantity", "trade_price"}, ...]
        """
        from broker.tastytrade import TastytradeAPIError, TastytradeClient
        from service.account_data_providers import resolve_tastytrade_account_number

        try:
            client = TastytradeClient.from_config()
            account_number = resolve_tastytrade_account_number(client)
            raw_positions = client.get_positions(account_number)
        except (TastytradeAPIError, ValueError) as e:
            # Same reasoning as before: this is the position list itself, not
            # a quote enrichment layer (contrast get_futures_quotes below) —
            # a fetch failure must not read as "no open futures", so it
            # propagates (TastytradeAPIError hits app.py's registered 502
            # handler; ValueError — missing/bad credentials — via FastAPI's
            # default handler).
            logger.error("Failed to fetch futures positions: %s", e)
            raise

        futures = []
        for position in raw_positions:
            if position.get("instrument-type") != "Future":
                continue
            symbol = position.get("symbol")
            if not symbol:
                continue

            try:
                root = client.get_future(symbol)["product-code"]
            except (TastytradeAPIError, KeyError) as e:
                # Best-effort fallback so a lookup hiccup doesn't drop the
                # position from the table entirely — bare contract symbol
                # (e.g. "ESM7") instead of the clean root ("ES").
                logger.error("Failed to resolve root symbol for future %s: %s", symbol, e)
                root = symbol.lstrip("/")

            quantity = float(position.get("quantity") or 0)
            direction = (position.get("quantity-direction") or "").strip().lower()
            signed_quantity = quantity if direction == "long" else -quantity
            avg_price = float(position.get("average-open-price") or 0)

            futures.append({
                "symbol": root,
                "quantity": f"{signed_quantity:,.0f}",
                "trade_price": f"${avg_price:,.2f}",
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

    def _get_open_futures_option_legs(self) -> list[dict]:
        """Currently-open futures-option positions (options on /ES, /NQ,
        etc.), sourced directly from Tastytrade's own positions endpoint —
        "Future Option" instrument-type entries, one dict per contract the
        broker already nets to a single signed quantity+price. Same rationale
        as get_futures_position(): Schwab's positions endpoint doesn't return
        these at all, but Tastytrade's does, so no transaction-history
        reconstruction is needed.

        Unlike the old transaction-derived legs, there is no "opened
        together" signal here (the broker only reports where things stand
        now, not how they got there) — a ratio spread shows as two
        independent contract rows instead of one merged row.

        symbol's trailing "<YYMMDD><P|C><strike>" segment (e.g.
        "./ESU6 E3DU6 260917P7480") is the only place strike/option-type live
        on a position row — confirmed against a live position matched to its
        option-chain contract (strike "7480" == that contract's
        strike-price "7480.0", unscaled, unlike equity OCC symbols).

        Returns: [{"symbol", "underlying_symbol", "expirationDate",
                   "strike_price", "option_type", "quantity", "open_price"}, ...]
        """
        from broker.tastytrade import TastytradeClient

        client = TastytradeClient.from_config()
        account_number = resolve_tastytrade_account_number(client)
        raw_positions = client.get_positions(account_number)

        legs = []
        for position in raw_positions:
            if position.get("instrument-type") != "Future Option":
                continue
            symbol = position.get("symbol")
            underlying = position.get("underlying-symbol")
            if not symbol or not underlying:
                continue

            strike_price, _, option_type = parse_tastytrade_future_option_symbol(symbol)
            if strike_price is None:
                continue

            try:
                root = client.get_future(underlying)["product-code"]
            except (TastytradeAPIError, KeyError) as e:
                logger.error("Failed to resolve root symbol for future option %s: %s", symbol, e)
                root = underlying.lstrip("/")

            # expires-at is only present on position rows (not transaction
            # records, which is why fetch_option_legs in
            # account_data_providers.py parses the date out of the symbol
            # instead) — preferred here since it's already authoritative,
            # no string-slicing needed.
            expires_at = position.get("expires-at") or ""
            expiration_date = expires_at[:10] if expires_at else None

            quantity = float(position.get("quantity") or 0)
            direction = (position.get("quantity-direction") or "").strip().lower()
            signed_quantity = quantity if direction == "long" else -quantity

            legs.append({
                "symbol": symbol,
                "underlying_symbol": root,
                "expirationDate": expiration_date,
                "strike_price": strike_price,
                "option_type": option_type,
                "quantity": signed_quantity,
                "open_price": float(position.get("average-open-price") or 0),
            })
        return legs

    def get_futures_option_position(self, lookback_days: int = 30):
        """Currently-open futures-option positions (options on /ES, /NQ,
        etc.) — see _get_open_futures_option_legs() for the source and its
        "no ratio-spread grouping" caveat.

        lookback_days is accepted but unused now — kept for signature
        compatibility with existing callers (the copilot tool) from when
        this reconstructed from a bounded transaction window; the positions
        endpoint always reflects whatever's open right now.

        Deliberately excludes current_price: pricing these requires Tastytrade's
        DXLink feed and can add several seconds per open expiration, so the
        frontend fetches that separately via get_futures_option_quotes() once
        this — the fast part — has already rendered.

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
        try:
            legs = self._get_open_futures_option_legs()
        except (TastytradeAPIError, ValueError) as e:
            # Same reasoning as get_futures_position above: this is the
            # position list, not the quote enrichment (get_futures_option_quotes),
            # so a failure here must surface as a system error, not "no open
            # futures options".
            logger.error("Failed to fetch futures option positions: %s", e)
            raise

        puts, calls = [], []
        for leg in legs:
            expiration_date = leg.get("expirationDate")
            days_to_expiry = None
            if expiration_date:
                try:
                    days_to_expiry = (datetime.strptime(expiration_date, "%Y-%m-%d").date() - date.today()).days
                except ValueError:
                    days_to_expiry = None

            multiplier = get_contract_multiplier(leg.get("underlying_symbol", ""))
            quantity = leg["quantity"]
            trade_price = leg["open_price"]
            # Same sign convention as the equity-option total_value: short
            # (negative quantity) shows a positive credit received, long
            # (positive quantity) shows a negative debit paid.
            total_value = trade_price * -quantity * multiplier

            option_details = {
                "ticker": leg.get("underlying_symbol"),
                "symbol": leg.get("symbol"),
                "strike_price": f"${leg.get('strike_price', 0):,.0f}",
                "expiration_date": expiration_date,
                "days_to_expiry": days_to_expiry,
                "quantity": f"{quantity:,.0f}",
                "trade_price": f"${trade_price:,.2f}",
                "total_value": total_value,
                # Carried through (rather than baked only into total_value) so
                # the frontend can price the *same* position at the live quote
                # once futuresQuotes loads, and derive P&L as the difference —
                # see futuresPnLColumn() in Positions.jsx.
                "multiplier": multiplier,
            }
            (puts if leg.get("option_type") == "PUT" else calls).append(option_details)
        return puts, calls

    def get_futures_option_quotes(self, lookback_days: int = 30) -> dict:
        """Live bid prices for currently-open futures-option positions, keyed
        by the same `symbol` legs carry in get_futures_option_position() —
        split out from that method so the position table itself can render
        immediately without waiting on Tastytrade's DXLink feed.
        """
        try:
            legs = self._get_open_futures_option_legs()
        except (TastytradeAPIError, ValueError) as e:
            logger.error("Failed to fetch futures option positions for quoting: %s", e)
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
        snapshot = self._require_snapshot()
        option_positions_details = []

        for position in snapshot["positions"]:
            if position["asset_type"] != "OPTION" or position["option_type"] != option_type:
                continue

            symbol = position["symbol"]
            ticker = position["underlying_symbol"]
            strike_price = position["strike_price"]
            expiration_date = position["expiration_date"]

            long_quantity = position["long_quantity"]
            short_quantity = position["short_quantity"]
            if long_quantity and long_quantity > 0:
                quantity = long_quantity
            elif short_quantity and short_quantity > 0:
                quantity = -short_quantity
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
                "trade_price": f"${position['average_price']:,.2f}",
                # Cost basis for now — get_current_price() (called by
                # every caller of this method) turns this into
                # unrealized P&L once the live quote is known.
                "total_value": (position["average_price"] or 0) * -quantity * 100
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
            quote_data = self.provider.get_quotes(ticker_list)
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
    def _calculate_exposure(cls, position: dict, strike_price):
        """Calculate exposure for PUT options."""
        exposure = 0
        short_quantity = position["short_quantity"]
        long_quantity = position["long_quantity"]

        if short_quantity and short_quantity > 0:
            exposure += strike_price * short_quantity * 100
        if long_quantity and long_quantity > 0:
            exposure -= strike_price * long_quantity * 100

        return exposure
