"""Live prices for contracts described broker-neutrally — the Market side
of pricing anything Schwab can't quote (futures, futures options), plus the
open option legs behind Transactions' unrealized P&L.

Contracts come in as (underlying, expiration, strike, type), not a broker
symbol, so callers never depend on Schwab's symbol format. Everything is a
display nicety layered onto positions that render without it: anything that
can't be priced is simply absent from the result, never an error.
"""

import logging
from datetime import date
from typing import Optional

from broker.tastytrade import TastytradeAPIError, TastytradeClient, get_shared_client
from service.shared.contracts import CONTRACT_MULTIPLIER

logger = logging.getLogger(__name__)

_TYPE_CODE = {"PUT": "P", "CALL": "C"}


def _futures_root(underlying: str) -> Optional[str]:
    """'/ES' or 'ES' -> 'ES' for a futures underlying; None for an equity.
    Both forms are accepted (see AGENTS.md's futures-symbol guardrail)."""
    root = underlying.lstrip("/").upper()
    return root if underlying.startswith("/") or root in CONTRACT_MULTIPLIER else None


def _mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    return round((bid + ask) / 2, 4) if bid is not None and ask is not None else None


class QuoteService:
    def __init__(self, client: Optional[TastytradeClient] = None):
        self._client = client

    def _get_client(self) -> Optional[TastytradeClient]:
        if self._client is None:
            try:
                self._client = get_shared_client()
            except ValueError as e:
                logger.error("Tastytrade credentials unavailable for quotes: %s", e)
        return self._client

    def quote_futures(self, roots: list[str]) -> dict[str, float]:
        """Live price per futures root ("ES" or "/ES" -> the front-month
        price), keyed by the root as given."""
        if not roots:
            return {}
        client = self._get_client()
        if client is None:
            return {}
        result = {}
        for root in dict.fromkeys(roots):
            try:
                result[root] = client.get_live_underlying_price(f"/{root.lstrip('/').upper()}")
            except (TastytradeAPIError, ValueError, TimeoutError) as e:
                logger.error("Failed to fetch live price for %s: %s", root, e)
        return result

    def quote_options(self, contracts: list[dict]) -> dict[str, dict]:
        """Live bid/ask/mid for option contracts, equity or futures:

            contracts: [{"key", "underlying", "expiration": date | "YYYY-MM-DD",
                         "strike", "type": "PUT" | "CALL"}, ...]
            returns:   {key: {"bid", "ask", "mid", "theta", "delta"}}
                       (theta per share per day, delta per share; None
                       when unknown)

        Each chain is fetched once — per underlying for equities (that chain
        covers every expiration), per (root, expiration) for futures options
        (Tastytrade's futures-option chain is per expiration) — and one
        DXLink snapshot covers every matched contract.
        """
        if not contracts:
            return {}
        client = self._get_client()
        if client is None:
            return {}

        equity: dict[str, list[dict]] = {}
        futures: dict[tuple[str, str], list[dict]] = {}
        for c in contracts:
            expiration = c["expiration"].isoformat() if isinstance(c["expiration"], date) else str(c["expiration"])
            c = {**c, "expiration": expiration}
            root = _futures_root(c["underlying"])
            if root:
                futures.setdefault((root, expiration), []).append(c)
            else:
                equity.setdefault(c["underlying"].upper(), []).append(c)

        matched = []
        keys_by_streamer: dict[str, list[str]] = {}

        def match(chain: list[dict], wanted: list[dict], with_expiration: bool):
            index = {}
            for contract in chain:
                try:
                    k = (float(contract["strike-price"]), contract["option-type"])
                    index[k + ((contract.get("expiration-date"),) if with_expiration else ())] = contract
                except (KeyError, TypeError, ValueError):
                    continue
            for c in wanted:
                k = (float(c["strike"]), _TYPE_CODE.get(c["type"]))
                contract = index.get(k + ((c["expiration"],) if with_expiration else ()))
                streamer = contract.get("streamer-symbol") if contract else None
                if not streamer:
                    continue
                if streamer not in keys_by_streamer:
                    matched.append(contract)
                keys_by_streamer.setdefault(streamer, []).append(c["key"])

        for ticker, wanted in equity.items():
            try:
                chain = client.get_option_chain(ticker)
            except TastytradeAPIError as e:
                logger.error("Failed to fetch option chain for %s: %s", ticker, e)
                continue
            match(chain, wanted, with_expiration=True)

        for (root, expiration), wanted in futures.items():
            try:
                chain = client.get_future_option_chain(f"/{root}", expiration_date=expiration)
            except (TastytradeAPIError, ValueError) as e:
                logger.error("Failed to fetch futures-option chain for /%s %s: %s", root, expiration, e)
                continue
            match(chain, wanted, with_expiration=False)

        if not matched:
            return {}
        try:
            quotes = client.get_chain_quotes(matched, with_theta=True)
        except TastytradeAPIError as e:
            logger.error("Failed to fetch option quotes: %s", e)
            return {}

        result = {}
        for streamer, keys in keys_by_streamer.items():
            quote = quotes.get(streamer)
            if not quote or (quote.get("bid") is None and quote.get("ask") is None):
                continue
            priced = {
                "bid": quote.get("bid"), "ask": quote.get("ask"), "mid": _mid(quote.get("bid"), quote.get("ask")),
                "theta": quote.get("theta"),
                "delta": quote.get("delta"),
            }
            for key in keys:
                result[key] = priced
        return result
