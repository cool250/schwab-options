import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Protocol

import pytz

from broker.schwab import Client
from broker.schwab.exceptions import BrokerAuthError, BrokerError
from broker.tastytrade import TastytradeAPIError, TastytradeClient

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
                           "call": {"symbol", "bid", "ask", "delta", "iv",
                                     "volume", "openInterest"} | None,
                           "put": {...} | None}, ...],
            }, or None if unavailable. Per-contract "iv"/"volume"/
            "openInterest" and the chain-level "iv" above are different
            things — chain-level is one ATM-derived figure for the whole
            chain, per-contract is that specific strike's own value.
        """
        ...

    def get_expirations(self, symbol: str, days_ahead: int = 60) -> list[dict]:
        """List every expiration date actually listed for `symbol` within the
        next `days_ahead` days.

        Returns:
            list[dict]: [{"date": "YYYY-MM-DD", "dte": int}, ...] sorted by dte.
        """
        ...

    def get_screener_contracts(
        self,
        symbol: str,
        min_dte: int,
        max_dte: int,
        option_types: list[str],
        min_otm_pct: float,
        max_otm_pct: float,
    ) -> Optional[dict]:
        """Every contract for `symbol` across *all* expirations within
        [min_dte, max_dte] whose strike falls inside the moneyness band —
        one fetch for the whole window, unlike get_option_chain() which
        resolves a single expiration. Backs the Options Screener page.

        `option_types`: subset of ["PUT", "CALL"]. Moneyness is percent
        out-of-the-money (positive = OTM, negative = ITM), mirrored per side
        — see strike_in_band().

        Returns:
            dict | None: {
                "symbol": str, "spot": float, "truncated": bool,
                "contracts": [{"symbol", "type": "PUT"|"CALL",
                               "expirationDate": "YYYY-MM-DD", "dte": int,
                               "strike", "bid", "ask", "delta",
                               "iv" (fraction, e.g. 0.25),
                               "volume", "openInterest"}, ...],
            }, or None if the symbol has no listed options.
        """
        ...


# Upper bound on contracts streamed per ticker in one screener snapshot. A
# daily-expiration underlying (SPY/QQQ, /ES) across a 60-DTE window with $1
# strikes can produce thousands of contracts in even a modest moneyness band
# — more than a single DXLink session reliably fills within its timeout.
# Over the cap, the contracts nearest ATM are kept (the highest-premium,
# so most ROI-relevant ones) and the result is flagged "truncated".
MAX_SCREENER_CONTRACTS = 600


def strike_in_band(strike: float, spot: float, option_type: str, min_otm_pct: float, max_otm_pct: float) -> bool:
    """Whether `strike` is within [min_otm_pct, max_otm_pct] percent OTM for
    `option_type` ("PUT"/"CALL"). OTM% is measured from spot in the direction
    that makes the option worthless: below spot for puts, above for calls —
    so "0 to 10" means "ATM out to 10% OTM" on either side, and a negative
    bound reaches into ITM strikes."""
    return min_otm_pct <= otm_pct(strike, spot, option_type) <= max_otm_pct


def otm_pct(strike: float, spot: float, option_type: str) -> float:
    if option_type == "PUT":
        return (spot - strike) / spot * 100
    return (strike - spot) / spot * 100


def _cap_contracts(contracts: list[dict], spot: float, key) -> tuple[list[dict], bool]:
    """Apply MAX_SCREENER_CONTRACTS, keeping the contracts whose strike
    (extracted via `key`) is nearest spot."""
    if len(contracts) <= MAX_SCREENER_CONTRACTS:
        return contracts, False
    return sorted(contracts, key=lambda c: abs(key(c) - spot))[:MAX_SCREENER_CONTRACTS], True


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
            # A fetch failure isn't the same as "this symbol has no listed
            # options" (which _normalize_chain can legitimately return None
            # for) — raise so it surfaces as a system error (app.py's
            # BrokerError handler -> 502) instead of masquerading as that.
            logger.error("Failed to fetch option chain for %s: %s", symbol, e)
            raise

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
            return {
                "symbol": option.symbol,
                "bid": option.bid,
                "ask": option.ask,
                "delta": option.delta,
                "iv": option.volatility,
                "volume": option.totalVolume,
                "openInterest": option.openInterest,
            }

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
            raise

        keys = set(option_chain.callExpDateMap or {}) | set(option_chain.putExpDateMap or {})
        expirations = []
        for key in keys:
            date_str, dte_str = key.split(":")
            expirations.append({"date": date_str, "dte": int(dte_str)})
        expirations.sort(key=lambda e: e["dte"])
        return expirations

    def get_screener_contracts(
        self,
        symbol: str,
        min_dte: int,
        max_dte: int,
        option_types: list[str],
        min_otm_pct: float,
        max_otm_pct: float,
    ) -> Optional[dict]:
        today = datetime.now(pytz.timezone("US/Eastern")).date()
        from_date = (today + timedelta(days=min_dte)).strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=max_dte)).strftime("%Y-%m-%d")
        contract_type = option_types[0] if len(option_types) == 1 else "ALL"

        try:
            # Schwab has no "strikes within X% of spot" filter on this
            # client, so over-fetch strikes and apply the moneyness band
            # below once the spot price is known from the response itself.
            option_chain = self.client.get_chain(
                symbol, from_date, to_date, strike_count=200, contract_type=contract_type
            )
        except BrokerAuthError:
            raise
        except BrokerError as e:
            logger.error("Failed to fetch screener chain for %s: %s", symbol, e)
            raise

        spot = option_chain.underlyingPrice
        if not spot:
            return None

        def clean(value: Optional[float]) -> Optional[float]:
            # Schwab reports -999 (and occasionally NaN) for greeks/IV it
            # couldn't compute, e.g. on a deep-ITM or zero-bid contract.
            if value is None or value != value or value <= -999:
                return None
            return value

        contracts = []
        for option_type, exp_map in (("CALL", option_chain.callExpDateMap), ("PUT", option_chain.putExpDateMap)):
            if option_type not in option_types:
                continue
            for key, strikes in (exp_map or {}).items():
                exp_date, dte = key.split(":")
                if not min_dte <= int(dte) <= max_dte:
                    continue
                for strike, options in strikes.items():
                    if not options or not strike_in_band(float(strike), spot, option_type, min_otm_pct, max_otm_pct):
                        continue
                    option = options[0]
                    iv = clean(option.volatility)
                    contracts.append({
                        "symbol": option.symbol,
                        "type": option_type,
                        "expirationDate": exp_date,
                        "dte": int(dte),
                        "strike": float(strike),
                        "bid": option.bid,
                        "ask": option.ask,
                        "delta": clean(option.delta),
                        # Schwab's per-contract volatility is in percent
                        # points (25.0); normalize to a fraction like
                        # Tastytrade's so the screener sees one unit.
                        "iv": iv / 100 if iv is not None else None,
                        "volume": option.totalVolume,
                        "openInterest": option.openInterest,
                    })

        contracts, truncated = _cap_contracts(contracts, spot, key=lambda c: c["strike"])
        return {"symbol": option_chain.symbol, "spot": spot, "truncated": truncated, "contracts": contracts}


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
            # Same reasoning as SchwabOptionChainProvider above: a fetch
            # failure must not read as "no listed options" — raise so
            # TastytradeAPIError hits app.py's 502 handler (ValueError/
            # TimeoutError here are rarer configuration/timeout cases and
            # still surface as a real error, just via FastAPI's default
            # handler instead of the branded one).
            logger.error("Failed to fetch option chain for %s: %s", symbol, e)
            raise

        if not contracts:
            return None

        try:
            snapshot = self.client.get_chain_snapshot(symbol, contracts, known_spot=spot)
            quotes, greeks = snapshot["quotes"], snapshot["greeks"]
            volume, open_interest = snapshot["volume"], snapshot["open_interest"]
        except TastytradeAPIError as e:
            logger.error("Failed to fetch chain quotes/greeks for %s: %s", symbol, e)
            quotes, greeks, volume, open_interest = {}, {}, {}, {}

        return self._normalize_chain(contracts, quotes, greeks, spot, volume, open_interest)

    def _normalize_chain(
        self,
        contracts: list[dict],
        quotes: dict[str, dict],
        greeks: dict[str, dict],
        spot: float,
        volume: Optional[dict[str, float]] = None,
        open_interest: Optional[dict[str, float]] = None,
    ) -> Optional[dict]:
        """Merge Tastytrade's flat contract list into the same strike-indexed
        shape SchwabOptionChainProvider produces."""
        volume = volume or {}
        open_interest = open_interest or {}

        def leg(contract: Optional[dict]) -> Optional[dict]:
            if contract is None:
                return None
            sym = contract.get("streamer-symbol")
            quote = quotes.get(sym, {})
            return {
                "symbol": sym,
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
                "delta": greeks.get(sym, {}).get("delta"),
                "iv": greeks.get(sym, {}).get("iv"),
                "volume": volume.get(sym),
                "openInterest": open_interest.get(sym),
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

        def contract_iv(contract: Optional[dict]) -> Optional[float]:
            if contract is None:
                return None
            return greeks.get(contract.get("streamer-symbol"), {}).get("iv")

        atm_strike = min(by_strike, key=lambda s: abs(s - spot), default=None)
        atm_ivs = []
        if atm_strike is not None:
            atm_sides = by_strike[atm_strike]
            for iv in (contract_iv(atm_sides.get("call")), contract_iv(atm_sides.get("put"))):
                if iv:
                    atm_ivs.append(iv)
        atm_iv = sum(atm_ivs) / len(atm_ivs) if atm_ivs else None

        return {
            "symbol": symbol_from_contracts(contracts),
            "spot": spot,
            "dte": int(actual_dte) if actual_dte is not None else None,
            "expirationDate": expiration_date,
            "iv": atm_iv,
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
            raise

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

    def get_screener_contracts(
        self,
        symbol: str,
        min_dte: int,
        max_dte: int,
        option_types: list[str],
        min_otm_pct: float,
        max_otm_pct: float,
    ) -> Optional[dict]:
        try:
            spot = self.client.get_live_underlying_price(symbol)
            contracts = self.client.get_options_chain(
                symbol,
                min_dte=min_dte,
                max_dte=max_dte,
                option_type=option_types[0].lower() if len(option_types) == 1 else "all",
                fetch_live_price=False,
            )
        except (TastytradeAPIError, ValueError, TimeoutError) as e:
            logger.error("Failed to fetch screener chain for %s: %s", symbol, e)
            raise

        def contract_type(contract: dict) -> str:
            return "PUT" if contract.get("option-type", "").upper().startswith("P") else "CALL"

        contracts = [
            c for c in contracts
            if c.get("streamer-symbol")
            and strike_in_band(float(c.get("strike-price", 0)), spot, contract_type(c), min_otm_pct, max_otm_pct)
        ]
        if not contracts:
            return None
        contracts, truncated = _cap_contracts(contracts, spot, key=lambda c: float(c.get("strike-price", 0)))

        try:
            # Longer timeout than a single-expiration chain load — a
            # multi-expiration screener snapshot can be several hundred
            # contracts, each needing its own Quote/Greeks/Summary event.
            snapshot = self.client.get_chain_snapshot(symbol, contracts, timeout=8.0, known_spot=spot)
        except TastytradeAPIError as e:
            logger.error("Failed to fetch screener quotes/greeks for %s: %s", symbol, e)
            raise

        quotes, greeks = snapshot["quotes"], snapshot["greeks"]
        volume, open_interest = snapshot["volume"], snapshot["open_interest"]
        rows = []
        for c in contracts:
            sym = c["streamer-symbol"]
            quote = quotes.get(sym, {})
            rows.append({
                "symbol": sym,
                "type": contract_type(c),
                "expirationDate": c.get("expiration-date"),
                "dte": c.get("days-to-expiration"),
                "strike": float(c.get("strike-price", 0)),
                "bid": quote.get("bid"),
                "ask": quote.get("ask"),
                "delta": greeks.get(sym, {}).get("delta"),
                "iv": greeks.get(sym, {}).get("iv"),
                "volume": volume.get(sym),
                "openInterest": open_interest.get(sym),
            })

        return {
            "symbol": symbol_from_contracts(contracts) or symbol,
            "spot": spot,
            "truncated": truncated,
            "contracts": rows,
        }


def symbol_from_contracts(contracts: list[dict]) -> Optional[str]:
    for contract in contracts:
        symbol = contract.get("underlying-symbol")
        if symbol:
            return symbol
    return None


def get_option_chain_provider() -> OptionChainProvider:
    """Select the option-chain provider based on the CHAIN_PROVIDER env var
    (set in .env). Defaults to Tastytrade."""
    provider = os.environ.get("CHAIN_PROVIDER", "tastytrade").strip().lower()
    if provider == "tastytrade":
        return TastytradeOptionChainProvider()
    if provider == "schwab":
        return SchwabOptionChainProvider()
    raise ValueError(f"Unknown CHAIN_PROVIDER {provider!r}; expected 'schwab' or 'tastytrade'")
