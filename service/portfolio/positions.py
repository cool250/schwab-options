from datetime import datetime, timedelta
from typing import Optional
import logging

from broker.exceptions import BrokerError
from utils.market_time import market_today
from service.portfolio.models import (
    Balances,
    FuturesOptionPosition,
    FuturesPosition,
    OptionPosition,
    SpreadLeg,
    StockPosition,
)
from service.portfolio.date_windows import open_position_lookback_days
from service.portfolio.ratio_spreads import group_open_ratio_spreads
from service.portfolio.transactions import TransactionService
from service.portfolio.providers import PositionProvider, get_position_provider
from service.shared.contracts import get_contract_multiplier
from utils.app_config import get_config

logger = logging.getLogger(__name__)


class PositionService:

    def __init__(self, provider: Optional[PositionProvider] = None):
        self.provider = provider or get_position_provider()
        # Fetched on first use, not here: the futures methods never need it,
        # so they shouldn't pay for (or fail on) the account snapshot call.
        self._snapshot: Optional[dict] = None

    def _require_snapshot(self) -> dict:
        """The account snapshot (balances + positions), fetched once. A
        broker failure propagates — app.py turns BrokerAuthError into a 503
        and BrokerError into a 502 — rather than reading as an empty
        portfolio."""
        if self._snapshot is None:
            self._snapshot = self.provider.get_account_snapshot()
        return self._snapshot

    # --- Top-level aggregator ---

    def populate_positions(self) -> tuple[tuple[list[OptionPosition], list[OptionPosition]], Balances, list[StockPosition]]:
        """Populate option positions with current prices, total exposure, and account balances.

        Deliberately excludes futures/futures-options — those are derived from
        transaction history (see get_futures_position/get_futures_option_position),
        which is slower, so the frontend only fetches them when the user
        opens the Futures tab, not on every equity-tab page load.
        """
        option_positions = self.get_option_position()
        account_balances = self.get_balances()
        stocks = self.get_stock_position()

        return option_positions, account_balances, stocks

    # --- Public getters ---

    def get_balances(self) -> Balances:
        """Cash (or the margin balance when negative), mutual funds, and the
        account's liquidation value — all None when the broker reports no
        balances section."""
        current = self._require_snapshot()["balances"]
        if current is None:
            return Balances()
        margin = current["margin_balance"]
        cash = current["cash_balance"]
        return Balances(
            cash_balance=cash if (margin is None or margin >= 0) else margin,
            mutual_fund_value=current["mutual_fund_value"],
            account_value=current["liquidation_value"],
            maintenance_requirement=current.get("maintenance_requirement"),
            buying_power=current.get("buying_power"),
            available_funds=current.get("available_funds"),
        )

    def get_stock_position(self) -> list[StockPosition]:
        """Stock and ETF positions, priced at the live quote."""
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
                "quantity": quantity,
                "trade_price": position["average_price"],
                "broker_cost_basis": broker_cost_basis,
                "broker_pl": broker_pl,
                "maintenance_requirement": position.get("maintenance_requirement"),
            })
        return [StockPosition(**s) for s in self.get_current_price(stocks)]

    def get_stock_trade_basis(self) -> dict[str, Optional[float]]:
        """{symbol: per-share price of each stock/ETF position as its own
        fills were priced, or None when history doesn't cover it}.

        Differs from Schwab's average_price for shares that came from an
        assignment: Schwab folds the option's premium into that price, while
        Reports already counts the premium as option P&L — valuing the shares
        at Schwab's price there would count it twice."""
        held = {}
        for position in self._require_snapshot()["positions"]:
            if position["asset_type"] not in ("EQUITY", "COLLECTIVE_INVESTMENT"):
                continue
            held[position["symbol"]] = position["long_quantity"] - position["short_quantity"]
        return TransactionService().get_stock_fill_costs(held)

    def get_futures_position(self, lookback_days: Optional[int] = None) -> list[FuturesPosition]:
        """Currently-open outright futures positions (e.g. root 'ES', 'NQ').

        Schwab's positions endpoint omits futures entirely, so these are
        FIFO-reconstructed from Schwab transaction history — a best-effort
        approximation bounded to the trailing lookback_days.

        No current_price: Schwab can't quote futures, so the page prices
        them through the Market quotes endpoint (POST /api/market/quotes).

        Returns:
            list: [{"symbol", "quantity", "trade_price"}, ...]
        """
        return self._get_futures_position_from_transactions(lookback_days or open_position_lookback_days())

    def _get_futures_position_from_transactions(self, lookback_days: int):
        """See get_futures_position(): reconstructs open futures positions by FIFO-matching
        transaction history (see TransactionService.get_equity_transactions)
        and netting whatever's left open per root symbol (e.g. 'ES', 'NQ').

        This is a best-effort reconstruction, not authoritative like the real
        positions endpoint, and only sees `lookback_days` back — kept short
        (30 days) by design rather than Schwab's ~1-year request cap, since a
        wider window risks surfacing a leg that actually closed outside it, or
        hit some matching edge case, as a stale "still open" position.
        """
        # +2 days: convert_to_iso8601 renders end_date as 00:00:00 UTC of that
        # calendar date. Tomorrow's midnight UTC is still only 5-8 PM in the US
        # today, so an evening (after-hours futures) fill would fall outside
        # the window until the date rolled over; the day after tomorrow covers it.
        end_date = (market_today() + timedelta(days=2)).strftime("%Y-%m-%d")
        start_date = (market_today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        # A failure propagates (502/503): this is the position list itself,
        # and must not read as "no open futures".
        trades = TransactionService().get_equity_transactions(
            "", start_date, end_date, asset_type="FUTURE", realized_gains_only=False,
            all_open=True,
        )

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
            futures.append(FuturesPosition(symbol=symbol, quantity=entry["quantity"], trade_price=avg_price))
        return futures

    def get_futures_option_position(self, lookback_days: Optional[int] = None) -> tuple[list[FuturesOptionPosition], list[FuturesOptionPosition]]:
        """Currently-open futures-option positions (options on /ES, /NQ, etc.).

        Reconstructed from Schwab transaction history (Schwab's positions
        endpoint omits futures options). Ratio-spread legs (buy 1 / sell 2+
        at a different strike, opened together) are merged into one row with
        both strikes shown in strike_price and a net entry price in
        trade_price. A grouped row's own `symbol` is synthetic and won't
        match a real quote, so it also carries `long_leg`/`short_leg` for the
        frontend's live Current Price calc — see
        service/portfolio/ratio_spreads.group_open_ratio_spreads.

        No current_price: Schwab can't quote futures options, so the page
        prices each contract (both legs of a grouped row) through the Market
        quotes endpoint (POST /api/market/quotes).

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
        return self._get_futures_option_position_from_transactions(lookback_days or open_position_lookback_days())

    def _get_open_futures_option_legs_from_transactions(self, lookback_days: int) -> list:
        """See get_futures_option_position(): reconstructed from transaction
        history, same rationale and lookback as get_futures_position(), since
        Schwab's positions endpoint doesn't return these either. Flat,
        ungrouped legs — pair with group_open_ratio_spreads() (see
        _get_futures_option_position_from_transactions below) when the
        caller wants ratio spreads merged."""
        # A failure propagates: this is the position list, not a quote layer.
        return TransactionService().get_open_futures_options(lookback_days=lookback_days)

    def _get_futures_option_position_from_transactions(self, lookback_days: int):
        """See get_futures_option_position(). Ratio-spread legs (opened
        together) are merged into one row via group_open_ratio_spreads, unless
        trades.group_ratio_spreads is off in config/app.properties — see
        _get_open_futures_option_legs_from_transactions() for the raw fetch."""
        legs = self._get_open_futures_option_legs_from_transactions(lookback_days)
        if get_config()["trades.group_ratio_spreads"]:
            legs = group_open_ratio_spreads(legs)

        puts, calls = [], []
        for leg in legs:
            expiration_date = leg.get("expirationDate")
            days_to_expiry = None
            if expiration_date:
                try:
                    days_to_expiry = (datetime.strptime(expiration_date, "%Y-%m-%d").date() - market_today()).days
                except ValueError:
                    days_to_expiry = None

            is_group = leg.get("strategy") == "RATIO_SPREAD"
            multiplier = get_contract_multiplier(leg.get("underlying_symbol", ""))
            common = {
                "ticker": leg.get("underlying_symbol"),
                "symbol": leg.get("symbol"),
                "expiration_date": expiration_date,
                "days_to_expiry": days_to_expiry,
                # Carried through (rather than baked only into total_value) so
                # the frontend can price the *same* position at the live quote
                # and derive P&L as the difference — see futuresPnLColumn()
                # in Positions.jsx.
                "multiplier": multiplier,
            }
            if is_group:
                net = leg.get("net_trade_price", 0)
                position = FuturesOptionPosition(
                    **common,
                    ratio=leg.get("ratio"),
                    trade_price=net,
                    # Both sides' quantities are already netted into `net`,
                    # so the multiplier is applied once rather than per leg.
                    total_value=net * multiplier,
                    # Each real leg's own symbol/quantity, for the page's live
                    # net Current Price — the group's `symbol` is synthetic.
                    long_leg=SpreadLeg(**leg["long_leg"]),
                    short_leg=SpreadLeg(**leg["short_leg"]),
                )
            else:
                price = leg.get("open_price", leg.get("price", 0))
                position = FuturesOptionPosition(
                    **common,
                    strike_price=leg.get("strike_price"),
                    quantity=leg.get("amount", 0),
                    trade_price=price,
                    # Short (negative amount) = credit received, positive;
                    # long = debit paid, negative.
                    total_value=price * -leg.get("amount", 0) * multiplier,
                )
            (puts if leg.get("option_type") == "PUT" else calls).append(position)
        return puts, calls

    def get_option_position(self) -> tuple[list[OptionPosition], list[OptionPosition]]:
        """Equity option positions (puts, calls), priced at the live quote."""
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

        return exposure_by_symbol

    # --- Private helpers ---

    def _get_positions_with_prices(self, option_type) -> list[OptionPosition]:
        """Options of one type ("P"/"C"), priced at the live quote."""
        return [OptionPosition(**o) for o in self.get_current_price(self.get_option_details(option_type))]

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
                days_to_expiry = (exp - market_today()).days
            else:
                days_to_expiry = None
            option_details = {
                "ticker": ticker,
                "symbol": symbol,
                "strike_price": strike_price,
                "expiration_date": expiration_date,
                "days_to_expiry": days_to_expiry,
                "quantity": quantity,
                "exposure": exposure,
                "trade_price": position["average_price"],
                # Cost basis for now — get_current_price() (called by
                # every caller of this method) turns this into
                # unrealized P&L once the live quote is known.
                "total_value": (position["average_price"] or 0) * -quantity * get_contract_multiplier(ticker),
                "maintenance_requirement": position.get("maintenance_requirement"),
            }
            option_positions_details.append(option_details)
        return option_positions_details

    def get_current_price(self, tickers):
        """Add the live price to each stock/option row.

        For options (identified by the presence of `total_value`, which
        stock entries don't carry), total_value is repurposed here from a
        trade-price cost basis into unrealized P&L — cost basis minus that
        same position priced at the live quote (short/credit positive,
        long/debit negative).

        A row with no quote gets current_price None and, for options,
        total_value None: its P&L is unknown. Pricing it at $0 instead would
        report a short option's whole premium as profit (a long's as a loss).
        """
        ticker_list = [ticker.get("symbol") for ticker in tickers if ticker.get("symbol")]
        # Option rows also get their underlying's price (one request for both).
        underlyings = sorted({t["ticker"] for t in tickers if "total_value" in t and t.get("ticker")})

        if not ticker_list:
            return tickers

        try:
            quote_data = self.provider.get_quotes(sorted(set(ticker_list) | set(underlyings)))
        except BrokerError as e:
            logger.error("Failed to fetch current prices: %s", e)
            quote_data = {}

        for ticker in tickers:
            current_price = quote_data.get(ticker.get("symbol"))
            ticker["current_price"] = current_price
            if "total_value" in ticker:
                ticker["underlying_price"] = quote_data.get(ticker.get("ticker"))
                if current_price is None:
                    ticker["total_value"] = None
                    continue
                quantity = ticker.get("quantity") or 0
                multiplier = get_contract_multiplier(ticker.get("ticker") or "")
                current_value = current_price * -quantity * multiplier
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
