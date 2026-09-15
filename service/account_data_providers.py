"""Account-data (positions/balances/transactions) providers — one
broker-neutral shape per concern, one implementation class per broker, same
pattern as service/option_chain_providers.py already uses for market data.

Deliberately excludes futures/futures-options *positions*: those aren't
part of any broker's real positions endpoint in this app (Schwab's doesn't
return them at all) — they're reconstructed from transaction history (via
the TransactionProvider below) and live-quoted via Tastytrade directly.
That reconstruction/live-quote logic stays in service/position.py and
service/transactions.py, untouched by this module.

This is the "switchable" model, not "aggregating": get_position_provider()/
get_transaction_provider() each return exactly one active provider,
selected by ACCOUNT_BROKER_PROVIDER — same shape as
get_option_chain_provider()'s BROKER_PROVIDER, kept as a separate env var
since account data has always defaulted to Schwab unconditionally,
independent of whichever broker market data is currently using.
"""

import logging
import os
from datetime import datetime
from typing import Optional, Protocol

from broker.schwab import Client
from broker.schwab.data.account_data import Position, SecuritiesAccount
from utils.utils import get_date_string

logger = logging.getLogger(__name__)

# Contract multipliers (points per contract) for non-standard underlyings —
# broker-neutral domain data (CME contract specs), not a Schwab-shape
# parsing detail, but colocated here since SchwabTransactionProvider needs
# it at parse time. TransactionService._get_multiplier delegates here too.
CONTRACT_MULTIPLIER = {
    "ES": 50,
    "NQ": 20,
}


def get_contract_multiplier(underlying_symbol: str) -> int:
    return CONTRACT_MULTIPLIER.get(underlying_symbol, 100)


def parse_option_symbol(symbol: str):
    """Parse an OCC equity option symbol into (ticker, strike_price, expiration_date).

    expiration_date is full 4-digit-year ISO ("2026-09-18"), matching the
    convention used everywhere else in the app (futures options,
    Transactions' expirationDate) — the OCC symbol itself only carries a
    2-digit year.
    """
    try:
        strike_price = float(symbol[13:21]) / 1000
        ticker = symbol[:6].strip()
        expiration_date = f"20{symbol[6:8]}-{symbol[8:10]}-{symbol[10:12]}"
        return ticker, strike_price, expiration_date
    except ValueError as e:
        logger.error(f"Error parsing option symbol {symbol}: {e}")
        return None, None, None


class PositionProvider(Protocol):
    def get_account_snapshot(self) -> dict:
        """Current balances + positions (equities, ETFs, options — not
        futures, see module docstring), normalized to a broker-neutral shape:

        {
          "balances": {
              "margin_balance": float | None,
              "cash_balance": float | None,
              "mutual_fund_value": float | None,
              "liquidation_value": float | None,
          } | None,   # None only if the account has no balances section at all
          "positions": [
              {
                  "asset_type": "EQUITY" | "OPTION" | "COLLECTIVE_INVESTMENT",
                  "symbol": str,                 # broker-native trading symbol
                  "long_quantity": float,
                  "short_quantity": float,
                  "average_price": float | None,
                  "tax_lot_long_price": float | None,
                  "tax_lot_short_price": float | None,
                  "long_open_pl": float | None,
                  "short_open_pl": float | None,
                  # Option-only (parsed from the option symbol); None for equities:
                  "underlying_symbol": str | None,
                  "strike_price": float | None,
                  "expiration_date": str | None,   # "YYYY-MM-DD"
                  "option_type": str | None,        # "P" | "C"
              }, ...
          ],
        }

        Raises BrokerAuthError/BrokerError on fetch failure — never returns
        partial data silently; callers decide how to degrade.
        """
        ...

    def get_quotes(self, symbols: list[str]) -> dict[str, float]:
        """Live mark price per symbol. Any symbol whose quote can't be
        fetched is simply omitted from the result."""
        ...


class SchwabPositionProvider:
    """Account-data fetching backed by broker.Client (Schwab)."""

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

    def get_quotes(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        quotes = self.client.get_price(",".join(symbols))
        return {
            symbol: asset.quote.mark
            for symbol, asset in getattr(quotes, "root", {}).items()
            if asset.quote and asset.quote.mark is not None
        }


def get_position_provider() -> PositionProvider:
    """Select the account-data provider based on the ACCOUNT_BROKER_PROVIDER
    env var (set in .env). Defaults to Schwab, matching this app's behavior
    before providers existed at all. Deliberately a separate knob from
    market data's BROKER_PROVIDER (which defaults to tastytrade) — account
    data has always been unconditionally Schwab, independent of whichever
    broker is serving option chains."""
    provider = os.environ.get("ACCOUNT_BROKER_PROVIDER", "schwab").strip().lower()
    if provider == "schwab":
        return SchwabPositionProvider()
    raise ValueError(f"Unknown ACCOUNT_BROKER_PROVIDER {provider!r}; expected 'schwab'")


class TransactionProvider(Protocol):
    def fetch_raw_transactions(self, start_date: str, end_date: str) -> list:
        """Broker-native transaction records, verbatim — backs the "raw
        transaction history" endpoint. Deliberately NOT normalized; shape is
        provider-specific by design, same as today's behavior. Must be
        JSON-serializable (a pydantic model or plain dict/list)."""
        ...

    def fetch_option_legs(self, start_date: str, end_date: str) -> list[dict]:
        """Every OPTION transfer item in the window, one dict per leg, not
        filtered by ticker/contract type (callers filter the result):
        {date, close_date, underlying_symbol, expirationDate, strike_price,
         symbol, price, amount, position_effect, option_type,
         type: "TRADE",   # broker-neutral "not yet triaged" sentinel —
                           # matching logic in the service promotes this to
                           # CLOSED/EXPIRED/ASSIGNED once a leg is matched
         close_event: "EXPIRATION" | "ASSIGNMENT" | None,
         total_amount, open_price, close_price, open_type}
        close_event is what replaces the old raw Schwab
        RECEIVE_AND_DELIVER-type + English-description sniffing
        _identify_trade_type used to do directly — computed once here, at
        parse time, instead."""
        ...

    def fetch_equity_future_legs(self, start_date: str, end_date: str) -> list[dict]:
        """Every EQUITY/FUTURE transfer item in the window, one dict per
        leg, not filtered by ticker/asset type (callers filter the result):
        {date, symbol, asset_type: "EQUITY"|"FUTURE", amount, price, cost}.
        cost is already multiplier-adjusted, credit-positive/debit-negative."""
        ...

    def normalize_futures_symbol(self, symbol: str) -> str:
        """Collapse a broker-native futures/futures-option symbol to its
        bare CME root (e.g. 'ES', 'NQ'). Non-futures symbols pass through
        unchanged. Exposed on the Protocol (not just an internal parsing
        detail) because TransactionService.get_equity_transactions calls it
        on the *final* display symbol only after FIFO matching completes —
        matching itself stays keyed on the exact contract symbol throughout."""
        ...


class SchwabTransactionProvider:
    """Transaction-history fetching backed by broker.Client (Schwab)."""

    # Futures prefix rules: first letter after stripping '/' → root symbol
    _FUTURES_PREFIX_MAP = {
        "E": "ES",
        "Q": "NQ",
    }

    def __init__(self, client: Optional[Client] = None):
        self.client = client or Client()

    def fetch_raw_transactions(self, start_date: str, end_date: str) -> list:
        return self.client.fetch_transactions(start_date=start_date, end_date=end_date)

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
        """Relocated verbatim from the old _identify_trade_type — same
        RECEIVE_AND_DELIVER + English-description sniffing, just computed
        once at parse time instead of every time a caller needs to know a
        leg's status. Returns None for a normal trade (not a close-event
        at all); the service maps EXPIRATION/ASSIGNMENT to its own
        EXPIRED/ASSIGNED/CLOSED vocabulary."""
        if raw_type != "RECEIVE_AND_DELIVER":
            return None
        if "Expiration" in description:
            return "EXPIRATION"
        if "Assignment" in description:
            return "ASSIGNMENT"
        logger.warning(
            "Unrecognized RECEIVE_AND_DELIVER description for %s: %r — treating as CLOSED",
            symbol, description
        )
        return None

    def fetch_option_legs(self, start_date: str, end_date: str) -> list[dict]:
        # Local import: OptionTransaction lives on the service module, and
        # importing it at module level here would make service/transactions.py
        # -> service/account_data_providers.py -> service/transactions.py a
        # circular import.
        from service.transactions import OptionTransaction

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
                    })
            except Exception as e:
                logger.error(f"Error processing equity/future transaction: {e}")
                continue

        return results


def get_transaction_provider() -> TransactionProvider:
    """Select the transaction-history provider based on the
    ACCOUNT_BROKER_PROVIDER env var — same knob get_position_provider()
    reads, since both are "account data" for the same broker account."""
    provider = os.environ.get("ACCOUNT_BROKER_PROVIDER", "schwab").strip().lower()
    if provider == "schwab":
        return SchwabTransactionProvider()
    raise ValueError(f"Unknown ACCOUNT_BROKER_PROVIDER {provider!r}; expected 'schwab'")
