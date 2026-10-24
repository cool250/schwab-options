"""Schwab's implementation of the Portfolio broker seam (see base.py).

Schwab specifics stay in this module: its SDK models, its symbol formats
(OCC equity options, '/QN3N26_P28500:XCME'-style futures options), and how
it records expirations, assignments and futures-option exercises.
"""

import logging
from datetime import datetime
from typing import Optional

from broker.schwab import Client
from broker.schwab.data.account_data import Position, SecuritiesAccount
from service.portfolio.date_windows import split_date_range
from service.portfolio.providers.base import OptionTransaction
from service.shared.contracts import get_contract_multiplier, parse_option_symbol
from utils.utils import get_date_string

logger = logging.getLogger(__name__)


class SchwabPositionProvider:
    """Balances, positions, quotes and accounts from Schwab (broker.schwab.Client)."""

    def __init__(self, client: Optional[Client] = None):
        self.client = client or Client()

    def get_account_snapshot(self) -> dict:
        account: SecuritiesAccount = self.client.fetch_positions()
        return {
            "balances": self._normalize_balances(account),
            "positions": self._normalize_positions(account),
        }

    def _normalize_balances(self, account: SecuritiesAccount) -> Optional[dict]:
        current = account.currentBalances
        if current is None:
            return None
        return {
            "margin_balance": current.marginBalance,
            "cash_balance": current.cashBalance,
            "mutual_fund_value": current.mutualFundValue,
            "liquidation_value": current.liquidationValue,
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
                "positions": a["positions"],
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
        # Schwab rejects a request spanning more than a year, so a longer
        # range (the equity lookback) is fetched a year at a time. A record
        # stamped exactly at a window boundary can come back twice — keep one.
        windows = split_date_range(start_date, end_date)
        if len(windows) == 1:
            return self.client.fetch_transactions(start_date=start_date, end_date=end_date)
        records, seen = [], set()
        for window_start, window_end in windows:
            for record in self.client.fetch_transactions(start_date=window_start, end_date=window_end):
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
        transactions = self.fetch_raw_transactions(start_date, end_date)
        parsed_transactions = []
        for transaction in transactions:
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
                    ).model_dump())
            except Exception as e:
                logger.error(f"Error processing transaction: {e}")
                continue

        return parsed_transactions

    def fetch_equity_future_legs(self, start_date: str, end_date: str) -> list[dict]:
        transactions = self.fetch_raw_transactions(start_date, end_date)
        results = []
        for transaction in transactions:
            try:
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

                    results.append({
                        "date": trade_date_str,
                        "symbol": symbol,
                        "asset_type": asset,
                        "amount": amount,
                        "price": float(getattr(item, "price", 0) or 0),
                        # Schwab's own `cost` already nets in the contract multiplier
                        # (e.g. $50/point for ES) and is credit-positive / debit-negative.
                        "cost": float(getattr(item, "cost", 0) or 0),
                        "position_effect": getattr(item, "positionEffect", None),
                    })
            except Exception as e:
                logger.error(f"Error processing equity/future transaction: {e}")
                continue

        return results
