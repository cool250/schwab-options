import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Protocol

import pytz

from broker import Client
from broker.exceptions import BrokerAuthError, BrokerError
from tasty_clients import TastytradeAPIError, TastytradeClient

logger = logging.getLogger(__name__)


class OptionChainProvider(Protocol):
    def get_option_chain(self, symbol: str, dte: int, strike_count: int = 20) -> Optional[dict]:
        """Fetch a normalized option chain (calls + puts merged by strike) for
        the expiration closest to `dte` days out.

        Returns:
            dict | None: {
                "symbol": str, "spot": float, "dte": int, "expirationDate": str,
                "iv": float,
                "chain": [{"strikePrice": float,
                           "call": {"symbol", "bid", "ask", "delta"} | None,
                           "put": {"symbol", "bid", "ask", "delta"} | None}, ...],
            }, or None if unavailable.
        """
        ...

    def get_expirations(self, symbol: str, days_ahead: int = 60) -> list[dict]:
        """List every expiration date actually listed for `symbol` within the
        next `days_ahead` days.

        Returns:
            list[dict]: [{"date": "YYYY-MM-DD", "dte": int}, ...] sorted by dte.
        """
        ...


class SchwabOptionChainProvider:
    """Options-chain fetching backed by broker.Client (Schwab)."""

    def __init__(self, client: Optional[Client] = None):
        self.client = client or Client()

    def get_option_chain(self, symbol: str, dte: int, strike_count: int = 20) -> Optional[dict]:
        today = datetime.now(pytz.timezone("US/Eastern")).date()
        from_date = (today + timedelta(days=max(dte - 4, 0))).strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=dte + 4)).strftime("%Y-%m-%d")

        try:
            # Schwab's strikeCount returns that many strikes total (split across
            # both sides of ATM), not per side, so double the request to actually
            # get `strike_count` strikes above and below.
            option_chain = self.client.get_chain(
                symbol, from_date, to_date, strike_count=strike_count * 2, contract_type="ALL"
            )
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to fetch option chain for %s: %s", symbol, e)
            return None

        return self._normalize_chain(option_chain, dte)

    def _normalize_chain(self, option_chain, target_dte: int) -> Optional[dict]:
        """Merge Schwab's call/put expiration maps into a single strike-indexed chain
        for the expiration closest to `target_dte`."""

        def pick_expiration(exp_date_map):
            if not exp_date_map:
                return None, {}
            best_key = min(exp_date_map, key=lambda k: abs(int(k.split(":")[1]) - target_dte))
            return best_key, exp_date_map[best_key]

        def leg(options):
            option = options[0] if options else None
            if option is None:
                return None
            return {"symbol": option.symbol, "bid": option.bid, "ask": option.ask, "delta": option.delta}

        call_key, call_strikes = pick_expiration(option_chain.callExpDateMap)
        put_key, put_strikes = pick_expiration(option_chain.putExpDateMap)
        key = call_key or put_key
        if key is None:
            return None
        exp_date, actual_dte = key.split(":")

        strikes = sorted(set(call_strikes) | set(put_strikes), key=float)
        merged = [
            {
                "strikePrice": float(strike),
                "call": leg(call_strikes.get(strike)),
                "put": leg(put_strikes.get(strike)),
            }
            for strike in strikes
        ]

        def contract_iv(options):
            option = options[0] if options else None
            return option.volatility if option else None

        # Schwab's chain-level `volatility` field is a dead placeholder (always ~29
        # regardless of symbol); use the ATM contract's own IV instead, which is
        # computed per-strike and actually varies by symbol.
        atm_strike = min(strikes, key=lambda s: abs(float(s) - option_chain.underlyingPrice), default=None)
        atm_ivs = []
        if atm_strike is not None:
            for iv in (contract_iv(call_strikes.get(atm_strike)), contract_iv(put_strikes.get(atm_strike))):
                if iv:
                    atm_ivs.append(iv)
        atm_iv = sum(atm_ivs) / len(atm_ivs) if atm_ivs else 0

        return {
            "symbol": option_chain.symbol,
            "spot": option_chain.underlyingPrice,
            "dte": int(actual_dte),
            "expirationDate": exp_date,
            "iv": atm_iv / 100,
            "chain": merged,
        }

    def get_expirations(self, symbol: str, days_ahead: int = 60) -> list[dict]:
        today = datetime.now(pytz.timezone("US/Eastern")).date()
        from_date = today.strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        try:
            # strike_count=1 keeps this lightweight — we only need the
            # expiration-date keys, not the actual option contracts.
            option_chain = self.client.get_chain(
                symbol, from_date, to_date, strike_count=1, contract_type="ALL"
            )
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to fetch expirations for %s: %s", symbol, e)
            return []

        keys = set(option_chain.callExpDateMap or {}) | set(option_chain.putExpDateMap or {})
        expirations = []
        for key in keys:
            date_str, dte_str = key.split(":")
            expirations.append({"date": date_str, "dte": int(dte_str)})
        expirations.sort(key=lambda e: e["dte"])
        return expirations


class TastytradeOptionChainProvider:
    """Options-chain fetching backed by TastytradeClient."""

    def __init__(self, client: Optional[TastytradeClient] = None):
        self.client = client or TastytradeClient.from_config()

    def get_option_chain(self, symbol: str, dte: int, strike_count: int = 20) -> Optional[dict]:
        try:
            spot = self.client.get_live_underlying_price(symbol)
            # Tastytrade's num_strikes keeps the N strikes closest to the
            # underlying total (not per side), so double it to match Schwab's
            # "strike_count above/below ATM" convention.
            contracts = self.client.get_options_chain(
                symbol,
                dte=dte,
                option_type="all",
                num_strikes=strike_count * 2,
                underlying_price=spot,
                fetch_live_price=False,
            )
        except (TastytradeAPIError, ValueError, TimeoutError) as e:
            logger.error("Failed to fetch option chain for %s: %s", symbol, e)
            return None

        if not contracts:
            return None

        try:
            quotes = self.client.get_chain_quotes(contracts)
        except TastytradeAPIError as e:
            logger.error("Failed to fetch chain quotes for %s: %s", symbol, e)
            quotes = {}

        return self._normalize_chain(contracts, quotes, spot)

    def _normalize_chain(self, contracts: list[dict], quotes: dict[str, dict], spot: float) -> Optional[dict]:
        """Merge Tastytrade's flat contract list into the same strike-indexed
        shape SchwabOptionChainProvider produces."""

        def leg(contract: Optional[dict]) -> Optional[dict]:
            if contract is None:
                return None
            sym = contract.get("streamer-symbol")
            quote = quotes.get(sym, {})
            return {
                "symbol": sym,
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
                # Not available from Tastytrade's REST chain metadata.
                "delta": None,
            }

        by_strike: dict[float, dict[str, dict]] = {}
        expiration_date = None
        actual_dte = None
        for contract in contracts:
            strike = float(contract.get("strike-price", 0))
            option_type = contract.get("option-type", "").upper()
            side = "call" if option_type.startswith("C") else "put"
            by_strike.setdefault(strike, {})[side] = contract
            expiration_date = expiration_date or contract.get("expiration-date")
            actual_dte = actual_dte if actual_dte is not None else contract.get("days-to-expiration")

        if expiration_date is None:
            return None

        merged = [
            {
                "strikePrice": strike,
                "call": leg(sides.get("call")),
                "put": leg(sides.get("put")),
            }
            for strike, sides in sorted(by_strike.items())
        ]

        return {
            "symbol": symbol_from_contracts(contracts),
            "spot": spot,
            "dte": int(actual_dte) if actual_dte is not None else None,
            "expirationDate": expiration_date,
            # Not available from Tastytrade's REST chain metadata.
            "iv": None,
            "chain": merged,
        }

    def get_expirations(self, symbol: str, days_ahead: int = 60) -> list[dict]:
        try:
            is_future = symbol.strip().startswith("/")
            contracts = (
                self.client.get_future_option_chain(symbol)
                if is_future
                else self.client.get_option_chain(symbol)
            )
        except (TastytradeAPIError, ValueError) as e:
            logger.error("Failed to fetch expirations for %s: %s", symbol, e)
            return []

        by_date: dict[str, int] = {}
        for contract in contracts:
            date = contract.get("expiration-date")
            dte = contract.get("days-to-expiration")
            if date is None or dte is None or dte > days_ahead:
                continue
            by_date[date] = dte

        expirations = [{"date": date, "dte": dte} for date, dte in by_date.items()]
        expirations.sort(key=lambda e: e["dte"])
        return expirations


def symbol_from_contracts(contracts: list[dict]) -> Optional[str]:
    for contract in contracts:
        symbol = contract.get("underlying-symbol")
        if symbol:
            return symbol
    return None


def get_option_chain_provider() -> OptionChainProvider:
    """Select the option-chain provider based on the BROKER_PROVIDER env var
    (set in .env). Defaults to Tastytrade."""
    provider = os.environ.get("BROKER_PROVIDER", "tastytrade").strip().lower()
    if provider == "tastytrade":
        return TastytradeOptionChainProvider()
    if provider == "schwab":
        return SchwabOptionChainProvider()
    raise ValueError(f"Unknown BROKER_PROVIDER {provider!r}; expected 'schwab' or 'tastytrade'")
