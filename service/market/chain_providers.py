"""Option chains from Tastytrade — the only market-data source.

Every method raises SymbolNotFound or MarketDataError (service/market/
errors.py) for a failure, and returns None only for "nothing listed" — so a
broker outage is never mistaken for an empty chain.
"""

import logging
from typing import Optional, Protocol

from broker.tastytrade import TastytradeClient, get_shared_client
from service.market.errors import translate_errors
from service.shared.strategy_math import otm_pct

logger = logging.getLogger(__name__)


class OptionChainProvider(Protocol):
    def get_option_chain(
        self,
        symbol: str,
        dte: Optional[int] = None,
        strike_count: int = 20,
        expiration_date: Optional[str] = None,
        spot: Optional[float] = None,
    ) -> Optional[dict]:
        """A normalized option chain (calls + puts merged by strike) for one
        expiration: exactly `expiration_date` ("YYYY-MM-DD") when given,
        otherwise the listed expiration closest to `dte` days out.
        `strike_count` strikes each side of the money. `spot`: the
        underlying's price if the caller already has it (saves fetching it).

        Returns:
            dict | None: {
                "symbol": str, "spot": float, "dte": int, "expirationDate": str,
                "iv": float,
                "chain": [{"strikePrice": float,
                           "call": {"symbol", "bid", "ask", "delta", "iv",
                                     "volume", "openInterest"} | None,
                           "put": {...} | None}, ...],
            }, or None if nothing is listed for that expiration. Per-contract
            "iv" and the chain-level "iv" differ — chain-level is one
            ATM-derived figure, per-contract is that strike's own value.
        """
        ...

    def get_spot(self, symbol: str) -> float:
        """The underlying's live price."""
        ...

    def get_expirations(self, symbol: str, days_ahead: int = 60) -> list[dict]:
        """Every expiration listed for `symbol` within `days_ahead` days:
        [{"date": "YYYY-MM-DD", "dte": int}, ...] sorted by dte."""
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
        one fetch for the whole window. Backs the Options Screener.

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
            }, or None if nothing is listed in the window and band.
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
    `option_type` ("PUT"/"CALL") — so "0 to 10" means "ATM out to 10% OTM"
    on either side, and a negative bound reaches into ITM strikes."""
    return min_otm_pct <= otm_pct(strike, spot, option_type) <= max_otm_pct


def _cap_contracts(contracts: list[dict], spot: float) -> tuple[list[dict], bool]:
    """Apply MAX_SCREENER_CONTRACTS, keeping the strikes nearest spot."""
    if len(contracts) <= MAX_SCREENER_CONTRACTS:
        return contracts, False
    nearest = sorted(contracts, key=lambda c: abs(float(c.get("strike-price", 0)) - spot))
    return nearest[:MAX_SCREENER_CONTRACTS], True


def _contract_type(contract: dict) -> str:
    return "PUT" if contract.get("option-type", "").upper().startswith("P") else "CALL"


def symbol_from_contracts(contracts: list[dict]) -> Optional[str]:
    return next((c["underlying-symbol"] for c in contracts if c.get("underlying-symbol")), None)


def normalize_chain(contracts: list[dict], snapshot: dict, spot: float) -> Optional[dict]:
    """Merge Tastytrade's flat contract list and a DXLink snapshot
    (TastytradeClient.get_chain_snapshot) into the strike-indexed shape
    OptionChainProvider.get_option_chain documents. Also used by the live
    chain stream (api/market/stream.py), so both serve the same shape."""
    quotes, greeks = snapshot.get("quotes", {}), snapshot.get("greeks", {})
    volume, open_interest = snapshot.get("volume", {}), snapshot.get("open_interest", {})

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
        by_strike.setdefault(strike, {})["put" if _contract_type(contract) == "PUT" else "call"] = contract
        expiration_date = expiration_date or contract.get("expiration-date")
        actual_dte = actual_dte if actual_dte is not None else contract.get("days-to-expiration")
    if expiration_date is None:
        return None

    # Chain-level IV: the average of the at-the-money call's and put's.
    atm_strike = min(by_strike, key=lambda s: abs(s - spot), default=None)
    atm_ivs = []
    if atm_strike is not None:
        for contract in by_strike[atm_strike].values():
            iv = greeks.get(contract.get("streamer-symbol"), {}).get("iv")
            if iv:
                atm_ivs.append(iv)

    return {
        "symbol": symbol_from_contracts(contracts),
        "spot": spot,
        "dte": int(actual_dte) if actual_dte is not None else None,
        "expirationDate": expiration_date,
        "iv": sum(atm_ivs) / len(atm_ivs) if atm_ivs else None,
        "chain": [
            {"strikePrice": strike, "call": leg(sides.get("call")), "put": leg(sides.get("put"))}
            for strike, sides in sorted(by_strike.items())
        ],
    }


class TastytradeOptionChainProvider:
    """Option chains backed by the shared TastytradeClient. Contract lists
    come from the client's metadata cache; each load opens one DXLink
    session for the spot price and every contract's quote/greeks."""

    def __init__(self, client: Optional[TastytradeClient] = None):
        self._client = client

    @property
    def client(self) -> TastytradeClient:
        if self._client is None:
            self._client = get_shared_client()
        return self._client

    def contracts_for(self, symbol: str, dte: Optional[int] = None, expiration_date: Optional[str] = None) -> list[dict]:
        """One expiration's contract metadata (no quotes): exactly
        `expiration_date`, else the listing closest to `dte`."""
        if expiration_date is None and dte is None:
            raise ValueError("Pass dte or expiration_date")
        return self.client.get_options_chain(
            symbol, dte=None if expiration_date else dte, expiration_date=expiration_date, fetch_live_price=False
        )

    def get_option_chain(
        self,
        symbol: str,
        dte: Optional[int] = None,
        strike_count: int = 20,
        expiration_date: Optional[str] = None,
        spot: Optional[float] = None,
    ) -> Optional[dict]:
        with translate_errors(symbol, "Option chain"):
            contracts = self.contracts_for(symbol, dte, expiration_date)
            if not contracts:
                return None

            # Tastytrade-side num_strikes counts strikes in total, not per
            # side, so double it for "strike_count each side of the money".
            def select(price: float) -> list[dict]:
                return self.client.nearest_strikes(contracts, strike_count * 2, price)

            if spot is None:
                snapshot = self.client.get_spot_and_snapshot(symbol, select)
                chosen, spot = snapshot["contracts"], snapshot["spot"]
            else:
                chosen = select(spot)
                snapshot = self.client.get_chain_snapshot(symbol, chosen, known_spot=spot)
        return normalize_chain(chosen, snapshot, spot)

    def get_spot(self, symbol: str) -> float:
        with translate_errors(symbol, "Live price"):
            return self.client.get_live_underlying_price(symbol)

    def get_expirations(self, symbol: str, days_ahead: int = 60) -> list[dict]:
        with translate_errors(symbol, "Expirations"):
            contracts = (
                self.client.get_future_option_chain(symbol)
                if symbol.strip().startswith("/")
                else self.client.get_option_chain(symbol)
            )
        by_date: dict[str, int] = {}
        for contract in contracts:
            date, dte = contract.get("expiration-date"), contract.get("days-to-expiration")
            if date is not None and dte is not None and dte <= days_ahead:
                by_date[date] = dte
        return sorted(({"date": d, "dte": n} for d, n in by_date.items()), key=lambda e: e["dte"])

    def get_screener_contracts(
        self,
        symbol: str,
        min_dte: int,
        max_dte: int,
        option_types: list[str],
        min_otm_pct: float,
        max_otm_pct: float,
    ) -> Optional[dict]:
        with translate_errors(symbol, "Screener chain"):
            listed = [
                c for c in self.client.get_options_chain(
                    symbol,
                    min_dte=min_dte,
                    max_dte=max_dte,
                    option_type=option_types[0].lower() if len(option_types) == 1 else "all",
                    fetch_live_price=False,
                )
                if c.get("streamer-symbol")
            ]
            if not listed:
                return None
            truncated = []

            def select(spot: float) -> list[dict]:
                band = [
                    c for c in listed
                    if strike_in_band(float(c.get("strike-price", 0)), spot, _contract_type(c), min_otm_pct, max_otm_pct)
                ]
                capped, was_capped = _cap_contracts(band, spot)
                truncated.append(was_capped)
                return capped

            # Longer timeout than a single-expiration chain: a screener
            # snapshot can be several hundred contracts across expirations.
            snapshot = self.client.get_spot_and_snapshot(symbol, select, timeout=8.0)

        contracts, spot = snapshot["contracts"], snapshot["spot"]
        if not contracts:
            return None
        quotes, greeks = snapshot["quotes"], snapshot["greeks"]
        volume, open_interest = snapshot["volume"], snapshot["open_interest"]
        rows = []
        for c in contracts:
            sym = c["streamer-symbol"]
            quote = quotes.get(sym, {})
            rows.append({
                "symbol": sym,
                "type": _contract_type(c),
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
            "truncated": truncated[0] if truncated else False,
            "contracts": rows,
        }


def get_option_chain_provider() -> OptionChainProvider:
    """The option-chain provider. Market data is Tastytrade only — Schwab is
    the Portfolio broker and never serves chains."""
    return TastytradeOptionChainProvider()
