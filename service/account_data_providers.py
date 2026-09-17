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
get_option_chain_provider()'s CHAIN_PROVIDER, kept as a separate env var
since account data has always defaulted to Schwab unconditionally,
independent of whichever broker market data is currently using.
"""

import logging
import os
import re
from datetime import datetime
from typing import Optional, Protocol

from broker.schwab import Client
from broker.schwab.data.account_data import Position, SecuritiesAccount
from broker.tastytrade import TastytradeClient
from utils.utils import get_date_string

logger = logging.getLogger(__name__)


def _to_float(value) -> Optional[float]:
    """Tastytrade's JSON responses carry numeric fields as strings (for
    precision) — Schwab's pydantic models already hand back floats, so only
    the Tastytrade providers below need this."""
    return float(value) if value is not None else None

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


_TASTYTRADE_FUTURE_OPTION_RE = re.compile(r"(\d{6})([PC])([\d.]+)$")


def parse_tastytrade_future_option_symbol(symbol: str):
    """Parse a Tastytrade-native futures-option symbol into
    (strike_price, expiration_date, option_type) — e.g.
    "./ESU6 E3DU6 260917P7480" -> (7480.0, "2026-09-17", "PUT").

    Unlike an equity OCC symbol, strike isn't *1000-scaled (confirmed
    against a live option-chain contract: symbol "...260917P6845" matches
    that same contract's strike-price "6845.0" exactly) — the only place
    strike/expiration/type live on a Tastytrade *position* row (as opposed
    to a chain contract, which has them as separate fields); needed here too
    since transaction records carry the same bare `symbol` field.

    Returns (None, None, None) if the trailing "<YYMMDD><P|C><strike>"
    segment isn't found.
    """
    match = _TASTYTRADE_FUTURE_OPTION_RE.search(symbol or "")
    if not match:
        logger.warning("Could not parse Tastytrade futures-option symbol %r", symbol)
        return None, None, None
    date_code, option_code, strike_str = match.groups()
    expiration_date = f"20{date_code[0:2]}-{date_code[2:4]}-{date_code[4:6]}"
    option_type = "PUT" if option_code == "P" else "CALL"
    return float(strike_str), expiration_date, option_type


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


def resolve_tastytrade_account_number(client: TastytradeClient) -> str:
    """TASTY_ACCOUNT_NUMBER pins a specific account; otherwise the first
    account on these credentials is used, logging a warning if there's more
    than one so a multi-account customer notices the ambiguity instead of
    silently trading against the wrong account.

    Module-level (not just a TastytradePositionProvider method) since
    service/position.py's futures methods need this too — Tastytrade's
    positions endpoint is the only source of real futures/futures-option
    positions (Schwab's doesn't return them at all), so those methods fetch
    from Tastytrade directly regardless of which broker ACCOUNT_BROKER_PROVIDER
    currently has equity/option positions pointed at."""
    env_number = os.environ.get("TASTY_ACCOUNT_NUMBER", "").strip()
    if env_number:
        return env_number

    accounts = client.get_accounts()
    if not accounts:
        raise ValueError("No Tastytrade accounts found for these credentials")
    if len(accounts) > 1:
        logger.warning(
            "Multiple Tastytrade accounts found (%d); using the first one (%s). "
            "Set TASTY_ACCOUNT_NUMBER to pin a specific account.",
            len(accounts), accounts[0]["account"]["account-number"],
        )
    return accounts[0]["account"]["account-number"]


class TastytradePositionProvider:
    """Account-data fetching backed by TastytradeClient for balances/positions,
    but Schwab's Client for get_quotes() — Tastytrade's snapshot REST quote
    endpoints are unverified/broken (see TastytradeClient.get_quote's
    docstring), while Schwab's get_price() is already proven here via
    SchwabPositionProvider.get_quotes(). Both brokers accept the same OCC-style
    option symbols, so no symbol translation is needed between them."""

    def __init__(
        self,
        tasty_client: Optional[TastytradeClient] = None,
        schwab_client: Optional[Client] = None,
    ):
        self.client = tasty_client or TastytradeClient.from_config()
        self.schwab_client = schwab_client or Client()
        self._account_number: Optional[str] = None

    def _resolve_account_number(self) -> str:
        if not self._account_number:
            self._account_number = resolve_tastytrade_account_number(self.client)
        return self._account_number

    def get_account_snapshot(self) -> dict:
        account_number = self._resolve_account_number()
        balances = self.client.get_balances(account_number)
        positions = self.client.get_positions(account_number)
        return {
            "balances": self._normalize_balances(balances),
            "positions": self._normalize_positions(positions),
        }

    def _normalize_balances(self, balances: dict) -> Optional[dict]:
        if not balances:
            return None
        return {
            "margin_balance": _to_float(balances.get("margin-equity")),
            "cash_balance": _to_float(balances.get("cash-balance")),
            # Tastytrade has no mutual-fund concept — always None, matching
            # the Optional shape the PositionProvider Protocol declares.
            "mutual_fund_value": None,
            "liquidation_value": _to_float(balances.get("net-liquidating-value")),
        }

    def _normalize_positions(self, positions: list[dict]) -> list[dict]:
        if not positions:
            return []

        normalized = []
        for position in positions:
            instrument_type = position.get("instrument-type")
            symbol = position.get("symbol")

            if instrument_type == "Equity":
                if not symbol:
                    continue
                normalized.append(self._base_fields("EQUITY", symbol, position))
            elif instrument_type == "Equity Option":
                # Same validity check SchwabPositionProvider uses: a
                # malformed/too-short OCC symbol is silently skipped.
                if not symbol or len(symbol) <= 15:
                    continue
                ticker, strike_price, expiration_date = parse_option_symbol(symbol)
                if not ticker:
                    continue
                fields = self._base_fields("OPTION", symbol, position)
                fields.update({
                    "underlying_symbol": ticker,
                    "strike_price": strike_price,
                    "expiration_date": expiration_date,
                    "option_type": symbol[-9],
                })
                normalized.append(fields)
            # Future/Future Option/Cryptocurrency/etc. are out of scope for
            # this app today — see module docstring; silently excluded.
        return normalized

    @staticmethod
    def _base_fields(asset_type: str, symbol: str, position: dict) -> dict:
        quantity = _to_float(position.get("quantity")) or 0
        direction = (position.get("quantity-direction") or "").strip().lower()
        return {
            "asset_type": asset_type,
            "symbol": symbol,
            "long_quantity": quantity if direction == "long" else 0,
            "short_quantity": quantity if direction == "short" else 0,
            "average_price": _to_float(position.get("average-open-price")),
            # Tastytrade's positions endpoint doesn't return per-tax-lot cost
            # basis or live unrealized P&L the way Schwab's does — callers
            # already handle these as optional (service/position.py formats
            # tax-lot price conditionally and passes P&L through as-is).
            "tax_lot_long_price": None,
            "tax_lot_short_price": None,
            "long_open_pl": None,
            "short_open_pl": None,
            "underlying_symbol": None,
            "strike_price": None,
            "expiration_date": None,
            "option_type": None,
        }

    def get_quotes(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        quotes = self.schwab_client.get_price(",".join(symbols))
        return {
            symbol: asset.quote.mark
            for symbol, asset in getattr(quotes, "root", {}).items()
            if asset.quote and asset.quote.mark is not None
        }


def get_position_provider() -> PositionProvider:
    """Select the account-data provider based on the ACCOUNT_BROKER_PROVIDER
    env var (set in .env). Defaults to Schwab, matching this app's behavior
    before providers existed at all. Deliberately a separate knob from
    market data's CHAIN_PROVIDER (which defaults to tastytrade) — account
    data has always been unconditionally Schwab, independent of whichever
    broker is serving option chains."""
    provider = os.environ.get("ACCOUNT_BROKER_PROVIDER", "schwab").strip().lower()
    if provider == "schwab":
        return SchwabPositionProvider()
    if provider == "tastytrade":
        return TastytradePositionProvider()
    raise ValueError(f"Unknown ACCOUNT_BROKER_PROVIDER {provider!r}; expected 'schwab' or 'tastytrade'")


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


class TastytradeTransactionProvider:
    """Transaction-history fetching backed by TastytradeClient."""

    # Tastytrade's transaction-sub-type vocabulary for actual position-
    # changing trades (options, equities, and outright futures alike) —
    # excludes Dividend/Deposit/Withdrawal/Interest/Balance Adjustment and
    # the option-only removal sub-types (Assignment/Expiration), handled
    # separately in fetch_option_legs.
    _TRADE_SUBTYPES = {"Buy to Open", "Buy to Close", "Sell to Open", "Sell to Close"}

    def __init__(self, client: Optional[TastytradeClient] = None):
        self.client = client or TastytradeClient.from_config()
        self._account_number: Optional[str] = None
        # get_future() is a real HTTP call and the same contract symbol
        # recurs across many transactions in one fetch window — cache it
        # per provider instance rather than re-resolving every leg.
        self._future_root_cache: dict[str, str] = {}

    def _resolve_account_number(self) -> str:
        if not self._account_number:
            self._account_number = resolve_tastytrade_account_number(self.client)
        return self._account_number

    def fetch_raw_transactions(self, start_date: str, end_date: str) -> list:
        account_number = self._resolve_account_number()
        return self.client.get_transactions(account_number, start_date=start_date, end_date=end_date)

    def normalize_futures_symbol(self, symbol: str) -> str:
        """Resolve a Tastytrade futures/futures-option underlying symbol
        (e.g. '/ESU6') to its bare CME root ('ES') via the instruments API —
        confirmed live: TastytradeClient.get_future('/ESZ6')['product-code']
        == 'ES'. Non-futures symbols (no leading '/') pass through
        unchanged."""
        if not symbol or not symbol.startswith("/"):
            return symbol
        if symbol in self._future_root_cache:
            return self._future_root_cache[symbol]
        try:
            root = self.client.get_future(symbol)["product-code"]
        except (TastytradeAPIError, KeyError) as e:
            logger.error("Failed to resolve root symbol for %s: %s", symbol, e)
            root = symbol.lstrip("/")
        self._future_root_cache[symbol] = root
        return root

    def fetch_option_legs(self, start_date: str, end_date: str) -> list[dict]:
        transactions = self.fetch_raw_transactions(start_date, end_date)

        legs = []
        for item in transactions:
            instrument_type = item.get("instrument-type")
            if instrument_type not in ("Equity Option", "Future Option"):
                continue

            symbol = item.get("symbol") or ""
            sub_type = item.get("transaction-sub-type")
            underlying_symbol = self.normalize_futures_symbol(item.get("underlying-symbol") or "")

            if instrument_type == "Equity Option":
                _, strike_price, expiration_date = parse_option_symbol(symbol)
                option_type = None
                if strike_price is not None:
                    option_type = "CALL" if symbol[-9] == "C" else "PUT"
            else:
                strike_price, expiration_date, option_type = parse_tastytrade_future_option_symbol(symbol)
            if strike_price is None or not option_type:
                continue

            close_event = None
            if sub_type == "Assignment":
                close_event = "ASSIGNMENT"
            elif sub_type == "Expiration":
                close_event = "EXPIRATION"

            if close_event:
                # Assignment/Expiration "removal" transactions carry no
                # price/action at all — they always CLOSE whatever was
                # open, but don't say which direction. That barely matters
                # downstream: TransactionService._match_open_close derives
                # the matched leg's final signed amount from the *opening*
                # leg regardless, falling back to a quantity-mismatch
                # warning (not a wrong result) when this guess doesn't
                # match the open side. Assumed direction here: closing a
                # short — the dominant case for this app's covered-call/
                # cash-secured-put wheel strategy, where both assignment
                # and expiration are overwhelmingly what happens to a
                # position you sold (STO), not one you bought.
                position_effect = "CLOSING"
                amount = float(item.get("quantity") or 0)
                price = 0.0
                open_type = None
            elif sub_type in self._TRADE_SUBTYPES:
                position_effect = "OPENING" if "Open" in sub_type else "CLOSING"
                quantity = float(item.get("quantity") or 0)
                amount = quantity if "Buy" in sub_type else -quantity
                price = float(item.get("price") or 0)
                open_type = ("BTO" if "Buy" in sub_type else "STO") if position_effect == "OPENING" else None
            else:
                continue

            multiplier = get_contract_multiplier(underlying_symbol)
            legs.append({
                "date": item.get("transaction-date"),
                "close_date": expiration_date,
                "underlying_symbol": underlying_symbol,
                "expirationDate": expiration_date,
                "strike_price": strike_price,
                "symbol": symbol,
                "price": price,
                "amount": amount,
                "position_effect": position_effect,
                "option_type": option_type,
                "type": "TRADE",
                "close_event": close_event,
                "total_amount": price * -amount * multiplier,
                "open_price": price if position_effect == "OPENING" else 0.0,
                "close_price": price if position_effect == "CLOSING" else 0.0,
                "open_type": open_type,
            })
        return legs

    def fetch_equity_future_legs(self, start_date: str, end_date: str) -> list[dict]:
        transactions = self.fetch_raw_transactions(start_date, end_date)

        results = []
        for item in transactions:
            instrument_type = item.get("instrument-type")
            if instrument_type not in ("Equity", "Future"):
                continue
            sub_type = item.get("transaction-sub-type")
            if sub_type not in self._TRADE_SUBTYPES:
                # Excludes Dividend and other non-trade Equity money
                # movements — same as Schwab's `if amount == 0: continue`
                # served there, just keyed on sub-type instead since
                # Tastytrade's Dividend entries do carry a nonzero value.
                continue

            quantity = float(item.get("quantity") or 0)
            if quantity == 0:
                continue
            amount = quantity if "Buy" in sub_type else -quantity

            value = float(item.get("value") or 0)
            results.append({
                "date": item.get("transaction-date"),
                "symbol": item.get("symbol") or "",
                "asset_type": "EQUITY" if instrument_type == "Equity" else "FUTURE",
                "amount": amount,
                "price": float(item.get("price") or 0),
                # Tastytrade's `value` is already the total dollar value of
                # the fill including any contract multiplier (confirmed
                # live: a 2-lot /ES option fill at price 7.4 had value
                # "740.0" == 2 * 7.4 * 50) — credit-positive/debit-negative
                # via `value-effect`, matching what Schwab's own `cost`
                # field already gave us.
                "cost": value if item.get("value-effect") == "Credit" else -value,
            })
        return results


def get_transaction_provider() -> TransactionProvider:
    """Select the transaction-history provider based on the
    ACCOUNT_BROKER_PROVIDER env var — same knob get_position_provider()
    reads, since both are "account data" for the same broker account."""
    provider = os.environ.get("ACCOUNT_BROKER_PROVIDER", "schwab").strip().lower()
    if provider == "schwab":
        return SchwabTransactionProvider()
    if provider == "tastytrade":
        return TastytradeTransactionProvider()
    raise ValueError(f"Unknown ACCOUNT_BROKER_PROVIDER {provider!r}; expected 'schwab' or 'tastytrade'")
