"""TransactionService: fetches the account's transaction history from the
Portfolio broker (service/portfolio/providers) and turns it into trades.

The matching itself lives in pure modules — option_matching,
equity_matching, ratio_spreads, date_windows — so this class only fetches,
filters, and hands off. Live prices for open legs come from Market
(POST /api/market/quotes), combined in the page.
"""

import logging
from datetime import timedelta
from typing import Dict, List, Optional

from service.portfolio.date_windows import equity_lookback_days, expand_date_range, open_position_lookback_days
from service.portfolio.equity_matching import combine_equity_lots, cost_of_held_position, match_equity_fills
from service.portfolio.option_matching import match_option_trades
from service.portfolio.providers import TransactionProvider, get_transaction_provider
from service.shared.contracts import CONTRACT_MULTIPLIER
from utils.market_time import market_today
from utils.utils import get_date_object

logger = logging.getLogger(__name__)


class TransactionService:
    """Trades from the account's transaction history: matched option trades,
    equity/futures round trips, and the open futures-option legs Positions
    rebuilds from history."""

    def __init__(self, provider: Optional[TransactionProvider] = None):
        self.provider = provider or get_transaction_provider()

    def get_open_futures_options(self, lookback_days: Optional[int] = None) -> List[Dict]:
        """Currently-open futures-option positions (options on /ES, /NQ, etc.),
        reconstructed from transaction history — like outright futures, Schwab's
        positions endpoint doesn't return these either.

        Deliberately short-lookback (positions.open_lookback_days in
        config/app.properties, 30 by default — unlike the option
        matcher's usual 30-day-back/5-day-forward padding used elsewhere): a
        wider window risks surfacing a leg that was actually closed outside
        it — or hit some matching edge case — as if it were still open, since
        this only sees what's inside the fetch window.
        """
        # +2 days: convert_to_iso8601 renders end_date as 00:00:00 UTC of that
        # calendar date. Tomorrow's midnight UTC is still only 5-8 PM in the US
        # today, so an evening (after-hours futures) fill would fall outside
        # the window until the date rolled over; the day after tomorrow covers it.
        if lookback_days is None:
            lookback_days = open_position_lookback_days()
        end_date = (market_today() + timedelta(days=2)).strftime("%Y-%m-%d")
        start_date = (market_today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        parsed = self.provider.fetch_option_legs(start_date, end_date)

        if not parsed:
            return []

        matched = match_option_trades(parsed)

        return [
            trade for trade in matched
            if trade["type"] not in ("EXPIRED", "CLOSED", "ASSIGNED", "EXERCISED")
            and trade["underlying_symbol"] in CONTRACT_MULTIPLIER
        ]

    def get_option_transactions(self, stock_ticker: str, start_date: str, end_date: str,
                             contract_type: str = "ALL", realized_gains_only: bool = True,
                             unrealized_only: bool = False) -> List[Dict]:
        """
        Fetch option transactions, match related trades, and calculate realized gains/losses.

        Args:
            stock_ticker (str): The ticker symbol to filter by (e.g., "AAPL")
            start_date (str): Start date in YYYY-MM-DD format
            end_date (str): End date in YYYY-MM-DD format
            contract_type (str, optional): Filter by option type - "PUT", "CALL", or "ALL". Defaults to "ALL"
            realized_gains_only (bool, optional): If True, only return closed positions. Defaults to True
            unrealized_only (bool, optional): If True, only return still-open positions
                (type == "TRADE") — takes precedence over realized_gains_only. Defaults to False

        Returns:
            list: Processed option transactions with calculated gains/losses
        """
        # Pad the range so a trade opened before it (or closed just after) can
        # still be matched; only trades closing inside the range are returned.
        expanded_date_range = expand_date_range(start_date, end_date)

        # Fetch every option leg in the expanded window
        option_transactions = self.provider.fetch_option_legs(
            expanded_date_range["start_date"], expanded_date_range["end_date"],
        )

        if not option_transactions:
            return []

        # The provider doesn't filter by ticker/contract type — narrow to
        # what was actually requested here. Ticker matching is deliberately
        # case-sensitive (no .upper()), same as this method's existing
        # convention; underlying_symbol is already the bare futures root
        # (e.g. "ES", not "/ES") courtesy of the provider's own normalization.
        if contract_type != "ALL":
            option_transactions = [t for t in option_transactions if t["option_type"] == contract_type]
        if stock_ticker:
            stock_ticker = stock_ticker.lstrip("/")
            option_transactions = [t for t in option_transactions if t["underlying_symbol"] == stock_ticker]

        # Match opening and closing trades
        matched_transactions = match_option_trades(option_transactions)

        # Filter by date range and calculate totals
        result_transactions = []
        for transaction in matched_transactions:
            if unrealized_only:
                # Only still-open legs — closed/expired/assigned ones have nothing left to unrealize
                if transaction["type"] != "TRADE":
                    continue
            # Skip if we only want realized gains and anything is still open
            elif realized_gains_only and transaction["type"] not in ["EXPIRED", "CLOSED", "ASSIGNED", "EXERCISED"]:
                continue

            # Only include transactions that closed within our original date range
            close_date_str = transaction.get("close_date", "")
            if close_date_str:
                close_date = get_date_object(close_date_str)
                if get_date_object(start_date) <= close_date <= get_date_object(end_date):
                    result_transactions.append(transaction)

        return result_transactions

    def get_stock_fill_costs(self, held: Dict[str, float]) -> Dict[str, Optional[float]]:
        """{symbol: per-share price of the shares held now, as their fills
        were priced (the strike, for shares from an assignment) — or None
        where the last equity_lookback_days of history doesn't account for
        the whole position}. `held`: {symbol: signed quantity}."""
        end = (market_today() + timedelta(days=2)).strftime("%Y-%m-%d")
        start = (market_today() - timedelta(days=equity_lookback_days())).strftime("%Y-%m-%d")
        fills = [f for f in self.provider.fetch_equity_future_legs(start, end) if f["asset_type"] == "EQUITY"]
        by_symbol: Dict[str, List[Dict]] = {}
        for fill in combine_equity_lots(fills):
            by_symbol.setdefault(fill["symbol"], []).append(fill)
        return {symbol: cost_of_held_position(by_symbol.get(symbol, []), qty) for symbol, qty in held.items()}

    def get_income_and_fees(self, start_date: str, end_date: str) -> List[Dict]:
        """Dividends, interest and trading fees dated start_date..end_date
        (inclusive), oldest first — see TransactionProvider.fetch_income_and_fees
        for the row shape."""
        # The request's end is midnight of end_date, so ask for one day more.
        fetch_end = (get_date_object(end_date) + timedelta(days=1)).strftime("%Y-%m-%d")
        rows = self.provider.fetch_income_and_fees(start_date, fetch_end)
        return sorted((r for r in rows if start_date <= r["date"] <= end_date), key=lambda r: r["date"])

    def get_equity_transactions(self, stock_ticker: str, start_date: str, end_date: str,
                                 asset_type: str = "ALL", realized_gains_only: bool = False,
                                 all_open: bool = False) -> List[Dict]:
        """
        Fetch FIFO-matched buy/sell round-trips for equities and outright futures
        contracts (i.e. the underlying instrument itself, not options on it).

        Unlike options, there's no strike/expiration to key a contract on, so
        opens and closes are matched by symbol alone, oldest-open-first — the
        standard FIFO cost-basis convention.

        Args:
            stock_ticker (str): Ticker/futures root to filter by (e.g. "AAPL", "ES"). Blank = all.
            start_date (str): Start date in YYYY-MM-DD format
            end_date (str): End date in YYYY-MM-DD format
            asset_type (str, optional): "EQUITY", "FUTURE", or "ALL". Defaults to "ALL"
            realized_gains_only (bool, optional): If True, only return closed round-trips.
            all_open (bool, optional): Also return every lot still open, however
                long ago it was opened (Positions' futures). Otherwise a trade is
                returned only when it was opened or closed in the range.

        Returns:
            list: [{"date" (opened), "close_date", "symbol", "asset_type", "quantity",
                     "open_price", "close_price", "total_amount", "status"}, ...]
        """
        # Positions can sit open far longer than a weekly option, so look back
        # further than the options matcher does for the opening lot — the full
        # lookback whatever the range, not shrunk to fit one Schwab request
        # (the provider fetches a long window a year at a time). Shrinking it
        # once left a YTD report ~2 months of history, so stock held since
        # last year closed with no cost basis and its loss disappeared.
        expanded = expand_date_range(start_date, end_date, lookback_days=equity_lookback_days(),
                                     max_span_days=None)

        raw_trades = self.provider.fetch_equity_future_legs(expanded["start_date"], expanded["end_date"])

        if not raw_trades:
            return []

        # The provider doesn't filter by ticker/asset type — narrow to what
        # was actually requested here. Ticker matching is case-insensitive
        # (unlike get_option_transactions'), and compares against each leg's *normalized*
        # futures root so a caller-supplied "ES" matches a raw '/ESU26:XCME'
        # symbol the same way it always has.
        if asset_type != "ALL":
            raw_trades = [t for t in raw_trades if t["asset_type"] == asset_type]
        if stock_ticker:
            stock_ticker_norm = stock_ticker.upper().lstrip("/")
            raw_trades = [
                t for t in raw_trades
                if stock_ticker_norm == self.provider.normalize_futures_symbol(t["symbol"])
            ]

        combined = combine_equity_lots(raw_trades)
        matched = match_equity_fills(combined)

        results = []
        for trade in matched:
            if realized_gains_only and not trade["closed"]:
                continue
            # A negative-quantity unmatched *futures* leg is most likely a
            # closing trade whose opening fill fell outside the lookback window
            # above (futures tags are unreliable, so the matcher queues it by
            # sign) — its own date is the close date, not an open date.
            # Stock fills follow their reliable OPENING/CLOSING tags: a
            # negative open stock lot is a real short (open, no close date),
            # and a close with no open comes back with its own close_date.
            is_futures_orphan = trade.get("quantity", 0) < 0 and trade["asset_type"] != "EQUITY"
            close_date_str = trade.get("close_date") or (trade["date"] if is_futures_orphan else "")
            open_date_str = "" if is_futures_orphan else (trade.get("date") or "")
            # Realized P&L belongs to the range it was closed in; otherwise a
            # trade shows when it was opened or closed in the range — a lot
            # opened before the range and still open isn't listed.
            if realized_gains_only:
                in_range = bool(close_date_str) and self._in_range(close_date_str, start_date, end_date)
            else:
                in_range = any(d and self._in_range(d, start_date, end_date)
                               for d in (open_date_str, close_date_str))
            if not in_range and not (all_open and not trade["closed"]):
                continue
            # FIFO matching above stays keyed on the exact contract symbol (each
            # expiration is a distinct instrument); only the displayed symbol is
            # rolled up to its root here, e.g. '/ESU26:XCME' -> 'ES'.
            trade["symbol"] = self.provider.normalize_futures_symbol(trade["symbol"])
            results.append(trade)

        results.sort(key=lambda r: r.get("close_date") or r["date"])
        return results

    @staticmethod
    def _in_range(date_str: str, start_date: str, end_date: str) -> bool:
        return get_date_object(start_date) <= get_date_object(date_str) <= get_date_object(end_date)
