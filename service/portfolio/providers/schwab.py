"""Schwab's implementation of the Portfolio broker seam (see base.py).

Schwab specifics stay in this module: its SDK models, its symbol formats
(OCC equity options, '/QN3N26_P28500:XCME'-style futures options), and how
it records expirations, assignments and futures-option exercises.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from broker.request_context import all_accounts_selected
from broker.schwab import Client
from broker.schwab.data.account_data import Position, SecuritiesAccount
from service.portfolio.date_windows import split_date_range
from service.portfolio.providers.base import OptionTransaction
from service.shared.contracts import get_contract_multiplier, parse_option_symbol
from utils.utils import get_date_string

logger = logging.getLogger(__name__)


def _weekday_on_or_before(date_str: str) -> str:
    """The date itself, or the Friday before it if it's a weekend."""
    if not date_str:
        return date_str
    day = datetime.strptime(date_str, "%Y-%m-%d")
    return get_date_string(day - timedelta(days=max(day.weekday() - 4, 0)))


def _account_hashes(client) -> list[Optional[str]]:
    """The accounts a call reads: [None] — the request's selected account,
    which the client resolves itself — or, with All accounts chosen, every
    account's hashValue."""
    if not all_accounts_selected():
        return [None]
    return [a["hashValue"] for a in client.list_accounts()] or [None]


def _combine_balances(balances: list[Optional[dict]]) -> Optional[dict]:
    """Every balance added across accounts. net_liquidity too: Schwab's
    aggregatedBalance is per account (it plus its own futures account), not
    a total of the login's accounts."""
    present = [b for b in balances if b]
    if not present:
        return None
    out = {}
    for key in present[0]:
        values = [b[key] for b in present if b.get(key) is not None]
        out[key] = sum(values) if values else None
    return out


def _combine_positions(positions: list[dict]) -> list[dict]:
    """The same holding in several accounts as one position: quantities,
    P&L and margin added, prices averaged by quantity."""
    merged: dict = {}
    for p in positions:
        key = (p["asset_type"], p["symbol"])
        if key not in merged:
            merged[key] = dict(p)
            continue
        m = merged[key]
        for side, price_keys in (("long_quantity", ("average_price", "tax_lot_long_price")),
                                 ("short_quantity", ("tax_lot_short_price",))):
            old_qty, new_qty = m[side] or 0, p[side] or 0
            for k in price_keys:
                if p.get(k) is not None and new_qty:
                    m[k] = p[k] if m.get(k) is None or not old_qty else (m[k] * old_qty + p[k] * new_qty) / (old_qty + new_qty)
        # average_price covers whichever side is held: a short-only holding
        # is averaged by its short quantity.
        if not (m["long_quantity"] or p["long_quantity"]) and p.get("average_price") is not None:
            old_qty, new_qty = m["short_quantity"] or 0, p["short_quantity"] or 0
            m["average_price"] = (p["average_price"] if m.get("average_price") is None or not old_qty
                                  else (m["average_price"] * old_qty + p["average_price"] * new_qty) / (old_qty + new_qty))
        for k in ("long_quantity", "short_quantity", "long_open_pl", "short_open_pl", "maintenance_requirement"):
            if p.get(k) is not None:
                m[k] = (m.get(k) or 0) + p[k]
    return list(merged.values())


class SchwabPositionProvider:
    """Balances, positions, quotes and accounts from Schwab (broker.schwab.Client)."""

    def __init__(self, client: Optional[Client] = None):
        self.client = client or Client()

    def get_account_snapshot(self) -> dict:
        hashes = _account_hashes(self.client)
        if hashes == [None]:
            account: SecuritiesAccount = self.client.fetch_positions()
            return {
                "balances": self._normalize_balances(account),
                "positions": self._normalize_positions(account),
            }
        # All accounts: each one read, then combined.
        accounts = [self.client.fetch_positions(account_hash=h) for h in hashes]
        return {
            "balances": _combine_balances([self._normalize_balances(a) for a in accounts]),
            "positions": _combine_positions([p for a in accounts for p in self._normalize_positions(a)]),
        }

    def _normalize_balances(self, account: SecuritiesAccount) -> Optional[dict]:
        current = account.currentBalances
        if current is None:
            return None
        return {
            "margin_balance": current.marginBalance,
            "cash_balance": current.cashBalance,
            "mutual_fund_value": current.mutualFundValue,
            "short_balance": current.shortBalance,
            "liquidation_value": current.liquidationValue,
            "net_liquidity": account.aggregatedBalance.liquidationValue if account.aggregatedBalance else None,
            "maintenance_requirement": current.maintenanceRequirement,
            "available_funds": current.availableFunds,
        }

    def _normalize_positions(self, account: SecuritiesAccount) -> list[dict]:
        if not account.positions:
            return []

        normalized = []
        for position in account.positions:
            if not position.instrument:
                continue
            asset_type = position.instrument.assetType
            symbol = position.instrument.symbol

            if asset_type in ("EQUITY", "COLLECTIVE_INVESTMENT"):
                if not symbol:
                    continue
                normalized.append(self._base_fields(asset_type, symbol, position))
            elif asset_type == "OPTION":
                # Same validity check get_option_details used inline before:
                # a malformed/too-short OCC symbol is silently skipped.
                if not symbol or len(symbol) <= 15:
                    continue
                ticker, strike_price, expiration_date = parse_option_symbol(symbol)
                if not ticker:
                    continue
                fields = self._base_fields(asset_type, symbol, position)
                fields.update({
                    "underlying_symbol": ticker,
                    "strike_price": strike_price,
                    "expiration_date": expiration_date,
                    "option_type": symbol[-9],
                })
                normalized.append(fields)
            # Any other assetType (e.g. FIXED_INCOME) is out of scope for
            # this app today, same as before this refactor — silently
            # excluded, not an error.
        return normalized

    @staticmethod
    def _base_fields(asset_type: str, symbol: str, position: Position) -> dict:
        return {
            "asset_type": asset_type,
            "symbol": symbol,
            "long_quantity": position.longQuantity or 0,
            "short_quantity": position.shortQuantity or 0,
            "average_price": position.averagePrice,
            "tax_lot_long_price": position.taxLotAverageLongPrice,
            "tax_lot_short_price": position.taxLotAverageShortPrice,
            "long_open_pl": position.longOpenProfitLoss,
            "short_open_pl": position.shortOpenProfitLoss,
            # Schwab's margin requirement for this position (0 for one fully
            # covered by another, e.g. a short put against short shares).
            "maintenance_requirement": position.maintenanceRequirement,
            "underlying_symbol": None,
            "strike_price": None,
            "expiration_date": None,
            "option_type": None,
        }

    def list_accounts(self) -> list[dict]:
        # Schwab's "hashValue" is its own opaque account id — safe for the
        # browser; the account number never leaves the server.
        return [
            {
                "id": a["hashValue"],
                "number": a["accountNumber"],
                "type": a["type"],
                "value": a["liquidationValue"],
            }
            for a in self.client.list_accounts()
        ]

    def get_quotes(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        quotes = self.client.get_price(",".join(symbols))
        return {
            symbol: asset.quote.mark
            for symbol, asset in getattr(quotes, "root", {}).items()
            if asset.quote and asset.quote.mark is not None
        }


class SchwabTransactionProvider:
    """Transaction history from Schwab (broker.schwab.Client)."""

    # Futures prefix rules: first letter after stripping '/' → root symbol
    _FUTURES_PREFIX_MAP = {
        "E": "ES",
        "Q": "NQ",
    }

    def __init__(self, client: Optional[Client] = None):
        self.client = client or Client()

    def fetch_raw_transactions(self, start_date: str, end_date: str) -> list:
        return [record for _, record in self._account_transactions(start_date, end_date)]

    def _account_transactions(self, start_date: str, end_date: str) -> list[tuple]:
        """(account, record) for every record in the window. account is
        None for the request's selected account; with All accounts chosen,
        each account's opaque hashValue (never its number — legs carry it to
        the browser), which the matchers keep apart so an open in one
        account never pairs with a close in another."""
        out = []
        for account_hash in _account_hashes(self.client):
            out += [(account_hash, record) for record in self._fetch_window(start_date, end_date, account_hash)]
        return out

    def _fetch_window(self, start_date: str, end_date: str, account_hash: Optional[str]) -> list:
        # Schwab rejects a request spanning more than a year, so a longer
        # range (the equity lookback) is fetched a year at a time. A record
        # stamped exactly at a window boundary can come back twice — keep one.
        account = {"account_hash": account_hash} if account_hash else {}
        windows = split_date_range(start_date, end_date)
        if len(windows) == 1:
            return self.client.fetch_transactions(start_date=start_date, end_date=end_date, **account)
        records, seen = [], set()
        for window_start, window_end in windows:
            for record in self.client.fetch_transactions(start_date=window_start, end_date=window_end, **account):
                activity_id = getattr(record, "activityId", None)
                if activity_id is not None:
                    if activity_id in seen:
                        continue
                    seen.add(activity_id)
                records.append(record)
        return records

    def normalize_futures_symbol(self, symbol: str) -> str:
        """Return the CME root symbol for a Schwab futures contract symbol.

        Handles two distinct notations that need different parsing:
        - A futures option's underlying, prefixed with '.' and starting with a
          single-letter product code that doesn't spell the root itself
          ('.QN4M26:XCME' → 'NQ', '.E3DM26_P7050:XCME' → 'ES') — looked up via
          _FUTURES_PREFIX_MAP.
        - An outright futures contract's own symbol, prefixed with '/', where
          the root IS spelled out in full before the 1-letter month code +
          2-digit year ('/ESU26:XCME' → 'ES', '/NQU26:XCME' → 'NQ') — taking
          just the first letter here would wrongly reduce 'NQU26' to 'N'.

        Non-futures symbols (no leading '.' or '/') are returned unchanged.
        """
        if not symbol:
            return symbol

        if symbol.startswith("/"):
            base = symbol.split(":")[0][1:]
            return base[:-3] if len(base) > 3 else base

        if symbol.startswith("."):
            base = symbol.split(":")[0][1:]
            first_letter = base[0] if base else ""
            root = self._FUTURES_PREFIX_MAP.get(first_letter)
            if not root:
                logger.warning("Could not resolve futures root for symbol %r", symbol)
                return symbol
            return root

        return symbol

    @staticmethod
    def _format_option_symbol(underlying_symbol: str, expiration_date: str, option_type: str, strike_price: float) -> str:
        """Build a standard OCC-style option symbol, e.g. 'SPY   260828P00758000'.

        Schwab returns futures options as broker-specific symbols (e.g.
        '/QN3N26_P28500:XCME') instead of OCC format, so this reconstructs the
        familiar '<root><YYMMDD><C/P><strike*1000, 8 digits>' layout from the
        parsed contract fields.
        """
        try:
            yymmdd = datetime.strptime(expiration_date, "%Y-%m-%d").strftime("%y%m%d")
        except (ValueError, TypeError):
            return underlying_symbol
        cp = "C" if option_type == "CALL" else "P"
        strike_str = f"{round(strike_price * 1000):08d}"
        return f"{underlying_symbol:<6}{yymmdd}{cp}{strike_str}"

    @staticmethod
    def _identify_close_event(raw_type: str, description: str, symbol: str) -> Optional[str]:
        """Classify a closing option leg from Schwab's transaction type and
        English description, once at parse time. Returns None for a normal
        trade (not a close-event at all); the service maps EXPIRATION/
        ASSIGNMENT/EXERCISE to its own EXPIRED/ASSIGNED/EXERCISED/CLOSED
        vocabulary.

        Equity options close by expiry or assignment through a
        RECEIVE_AND_DELIVER ("Removed due to Expiration|Assignment|Exercise
        …"). Futures options don't: Schwab books both as an ordinary TRADE
        that closes the option at $0 — "Exercise, future settle 2.0 of
        /NQZ26 …" or "Removal of option due to expiration of /ESZ26 …" — and
        delivers the future as a separate fill at the strike ("Opening
        futures position due to futures option expiration"). Without these
        checks an exercised futures option read as a buy/sell-to-close at
        $0: its whole premium a win (short) or a loss (long)."""
        description = description or ""
        if raw_type == "TRADE":
            if description.startswith("Exercise") and "future" in description:
                return "EXERCISE"
            if description.startswith("Removal of option due to expiration"):
                return "EXPIRATION"
            return None
        if raw_type != "RECEIVE_AND_DELIVER":
            return None
        if "Expiration" in description:
            return "EXPIRATION"
        # An equity exercise delivers shares the same way an assignment does.
        if "Assignment" in description or "Exercise" in description:
            return "ASSIGNMENT"
        logger.warning(
            "Unrecognized RECEIVE_AND_DELIVER description for %s: %r — treating as CLOSED",
            symbol, description
        )
        return None

    def fetch_option_legs(self, start_date: str, end_date: str) -> list[dict]:
        parsed_transactions = []
        for account, transaction in self._account_transactions(start_date, end_date):
            try:
                transfer_items = getattr(transaction, "transferItems", [])
                if transfer_items is None:
                    continue
                type_of_transaction = getattr(transaction, "type", "UNKNOWN")
                description = getattr(transaction, "description", "Trade")
                trade_date = getattr(transaction, "tradeDate", None)
                for item in transfer_items:
                    if not hasattr(item, "instrument") or item.instrument is None:
                        continue
                    if getattr(item.instrument, "assetType") != "OPTION":
                        continue

                    underlying_symbol = self.normalize_futures_symbol(
                        getattr(item.instrument, "underlyingSymbol")
                    )
                    option_type = getattr(item.instrument, "putCall")
                    symbol = getattr(item.instrument, "symbol", "") or ""
                    price = float(getattr(item, "price", 0))
                    strike_price = getattr(item.instrument, "strikePrice")
                    amount = float(getattr(item, "amount", 0))
                    position_effect = getattr(item, "positionEffect", None)

                    try:
                        expiration_date_obj = getattr(item.instrument, "expirationDate", None)
                        expiration_date = get_date_string(expiration_date_obj) if expiration_date_obj else ""
                        trade_date_str = ""
                        if trade_date:
                            trade_date_str = get_date_string(trade_date)
                    except Exception as e:
                        logger.error(f"Error processing dates: {e}")
                        expiration_date = ""
                        trade_date_str = ""

                    # Futures options come back as broker-specific symbols (e.g.
                    # '/QN3N26_P28500:XCME') instead of Schwab's usual OCC-style
                    # equity option symbols — reformat to match. Schwab also
                    # sometimes omits the symbol entirely (returns null) on
                    # legitimate legs (seen on TRADE and RECEIVE_AND_DELIVER
                    # records), so synthesize one from the parsed fields rather
                    # than dropping the transaction.
                    if (not symbol or symbol.startswith("/")) and expiration_date:
                        symbol = self._format_option_symbol(
                            underlying_symbol, expiration_date, option_type, strike_price
                        )

                    open_type = None
                    if position_effect == "OPENING":
                        open_type = "BTO" if amount > 0 else "STO"

                    close_event = self._identify_close_event(type_of_transaction, description, symbol)

                    parsed_transactions.append(OptionTransaction(
                        date=trade_date_str,
                        close_date=expiration_date,
                        underlying_symbol=underlying_symbol,
                        expirationDate=expiration_date,
                        strike_price=strike_price,
                        symbol=symbol,
                        price=price,
                        amount=amount,
                        position_effect=position_effect,
                        option_type=option_type,
                        type="TRADE",
                        close_event=close_event,
                        total_amount=price * -amount * get_contract_multiplier(underlying_symbol),
                        open_price=price if position_effect == "OPENING" else 0.0,
                        close_price=price if position_effect == "CLOSING" else 0.0,
                        open_type=open_type,
                        account=account,
                    ).model_dump())
            except Exception as e:
                logger.error(f"Error processing transaction: {e}")
                continue

        return parsed_transactions

    @staticmethod
    def _income_category(description: str, amount: float) -> str:
        """What a DIVIDEND_OR_INTEREST record is, from Schwab's description:
        "SCHWAB1 INT 06/29-07/29" is interest earned on cash, "INTEREST
        02/26THRU 03/29" margin interest charged, a money fund's name its
        dividend, and any other name a stock dividend — received, or charged
        (negative) on shares held short."""
        text = (description or "").upper()
        if text.startswith("SCHWAB1 INT"):
            return "INTEREST"
        if text.startswith("INTEREST"):
            return "MARGIN_INTEREST"
        if "MONEY" in text:
            return "MONEY_FUND_DIVIDEND"
        return "DIVIDEND" if amount >= 0 else "SHORT_DIVIDEND"

    def fetch_income_and_fees(self, start_date: str, end_date: str) -> list[dict]:
        transactions = self.fetch_raw_transactions(start_date, end_date)
        rows = []
        for transaction in transactions:
            try:
                trade_date = getattr(transaction, "tradeDate", None)
                date = get_date_string(trade_date) if trade_date else ""
                kind = getattr(transaction, "type", None)
                description = getattr(transaction, "description", "") or ""
                if kind == "DIVIDEND_OR_INTEREST":
                    amount = float(getattr(transaction, "netAmount", 0) or 0)
                    rows.append({"date": date, "kind": "INCOME", "category": self._income_category(description, amount),
                                 "description": description, "amount": amount})
                elif kind == "TRADE":
                    # Each fee is its own transfer item, its cost negative.
                    for item in getattr(transaction, "transferItems", []) or []:
                        fee_type = getattr(item, "feeType", None)
                        cost = float(getattr(item, "cost", 0) or 0)
                        if fee_type and cost:
                            rows.append({"date": date, "kind": "FEE", "category": fee_type,
                                         "description": description, "amount": cost})
            except Exception as e:
                logger.error(f"Error processing income/fee transaction: {e}")
                continue
        return rows

    # Schwab's assetType → TransactionProvider.fetch_executions' asset_class.
    _FILL_ASSET_CLASS = {
        "OPTION": "OPTION",
        "FUTURE": "FUTURE",
        "EQUITY": "STOCK",
        "COLLECTIVE_INVESTMENT": "ETF",
        "MUTUAL_FUND": "FUND",
    }

    def fetch_executions(self, start_date: str, end_date: str) -> list[dict]:
        executions = []
        for _, transaction in self._account_transactions(start_date, end_date):
            # Equity expirations and assignments are RECEIVE_AND_DELIVER, not
            # executions. Futures-option expiries and exercises, the futures
            # they deliver, and assigned shares are TRADEs — but with no
            # order behind them: only a record with an orderId was placed.
            if getattr(transaction, "type", None) != "TRADE":
                continue
            trade_date = getattr(transaction, "tradeDate", None)
            executed = getattr(transaction, "time", None)
            order_id = getattr(transaction, "orderId", None)
            for item in getattr(transaction, "transferItems", []) or []:
                instrument = getattr(item, "instrument", None)
                asset = getattr(instrument, "assetType", None)
                # The cash side and fee lines are CURRENCY items, not executions.
                if not asset or asset == "CURRENCY":
                    continue
                is_option = asset == "OPTION"
                expiration = getattr(instrument, "expirationDate", None) if is_option else None
                symbol = getattr(instrument, "symbol", "") or ""
                executions.append({
                    "date": get_date_string(trade_date) if trade_date else "",
                    "time": executed.isoformat() if isinstance(executed, datetime) else None,
                    "order_id": str(order_id) if order_id is not None else None,
                    "placed": order_id is not None,
                    "asset_class": self._FILL_ASSET_CLASS.get(asset, "OTHER"),
                    "symbol": symbol.split(":")[0],
                    "underlying": self.normalize_futures_symbol(
                        getattr(instrument, "underlyingSymbol", None) if is_option else symbol
                    ) if (is_option or asset == "FUTURE") else symbol,
                    "expiration": get_date_string(expiration) if expiration else None,
                    "strike": getattr(instrument, "strikePrice", None) if is_option else None,
                    "option_type": getattr(instrument, "putCall", None) if is_option else None,
                    "quantity": float(getattr(item, "amount", 0) or 0),
                    "price": float(getattr(item, "price", 0) or 0),
                    "position_effect": getattr(item, "positionEffect", None),
                })
        return executions

    def fetch_equity_future_legs(self, start_date: str, end_date: str) -> list[dict]:
        results = []
        for account, transaction in self._account_transactions(start_date, end_date):
            try:
                # Only trades (assignments and exercises are trades too): a
                # transfer in (RECEIVE_AND_DELIVER) carries no price, and
                # taken as a fill it reads as shares bought for $0.
                if getattr(transaction, "type", None) != "TRADE":
                    continue
                transfer_items = getattr(transaction, "transferItems", []) or []
                trade_date = getattr(transaction, "tradeDate", None)
                trade_date_str = get_date_string(trade_date) if trade_date else ""

                for item in transfer_items:
                    instrument = getattr(item, "instrument", None)
                    if instrument is None:
                        continue

                    asset = getattr(instrument, "assetType", None)
                    # ETFs (IWM, SPY, QQQ shares) are COLLECTIVE_INVESTMENT
                    # to Schwab — stock for every purpose here.
                    if asset == "COLLECTIVE_INVESTMENT":
                        asset = "EQUITY"
                    if asset not in ("EQUITY", "FUTURE"):
                        continue

                    symbol = getattr(instrument, "symbol", "") or ""
                    amount = float(getattr(item, "amount", 0) or 0)
                    if amount == 0:
                        continue

                    # Shares from a Friday assignment carry Monday's tradeDate
                    # but Saturday's execution time. Going by tradeDate left
                    # the close out of a report run in between; a Saturday
                    # date goes back to Friday, the day it belongs to (the
                    # Reports calendars only draw weekdays). Futures keep
                    # tradeDate: their evening session is the next trade day.
                    executed = getattr(transaction, "time", None)
                    fill_date = trade_date_str
                    if asset == "EQUITY" and isinstance(executed, datetime):
                        fill_date = _weekday_on_or_before(min(trade_date_str, get_date_string(executed)))

                    results.append({
                        "date": fill_date,
                        "symbol": symbol,
                        "asset_type": asset,
                        "amount": amount,
                        "price": float(getattr(item, "price", 0) or 0),
                        # Schwab's own `cost` already nets in the contract multiplier
                        # (e.g. $50/point for ES) and is credit-positive / debit-negative.
                        "cost": float(getattr(item, "cost", 0) or 0),
                        "position_effect": getattr(item, "positionEffect", None),
                        "account": account,
                    })
            except Exception as e:
                logger.error(f"Error processing equity/future transaction: {e}")
                continue

        return results
