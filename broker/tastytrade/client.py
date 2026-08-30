"""
Python API client for the Tastytrade (tastyworks) API.

WARNING: Defaults to the PRODUCTION environment (api.tastyworks.com). Calls
made with production credentials act on a real, live brokerage account —
place_order() will submit real trades. Pass base_url=SANDBOX_BASE_URL to
target the cert/sandbox environment instead.

Auth model: Tastytrade's OAuth2 flow exchanges a long-lived refresh token
(+ client secret) for a short-lived access token. This client handles that
exchange and transparently refreshes the access token when it expires.

Usage:
    from broker.tastytrade import TastytradeClient

    client = TastytradeClient(
        client_secret="...",
        refresh_token="...",
    )

    # or, to pull credentials from config.py / env vars automatically:
    client = TastytradeClient.from_config()

    accounts = client.get_accounts()
    balances = client.get_balances(accounts[0]["account"]["account-number"])
    quote = client.get_quote("AAPL")
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import time
import warnings
from typing import Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

SANDBOX_BASE_URL = "https://api.cert.tastyworks.com"  # confirmed reachable; verified via live token exchange
PROD_BASE_URL = "https://api.tastyworks.com"
DEFAULT_BASE_URL = PROD_BASE_URL
OAUTH_TOKEN_PATH = "/oauth/token"


class TastytradeAPIError(Exception):
    """Raised when the Tastytrade API returns an error response."""

    def __init__(self, status_code: int, message: str, payload: Optional[dict] = None):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"[{status_code}] {message}")


class TastytradeClient:
    """Thin wrapper around the Tastytrade REST API (sandbox by default)."""

    def __init__(
        self,
        client_secret: str,
        refresh_token: str,
        client_id: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        print_json: bool = False,
    ):
        if not client_secret:
            raise ValueError("client_secret is required")
        if not refresh_token:
            raise ValueError("refresh_token is required")

        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.print_json = print_json

        self._access_token: Optional[str] = None
        self._access_token_expires_at: float = 0.0

        self.session = requests.Session()

    @classmethod
    def from_config(
        cls, base_url: str = DEFAULT_BASE_URL, timeout: float = 15.0, print_json: bool = False
    ) -> "TastytradeClient":
        """Build a client from TASTY_CLIENT_ID/TASTY_CLIENT_SECRET/TASTY_REFRESH_TOKEN
        env vars, falling back to CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN in config.py
        (gitignored)."""
        try:
            import config as local_config
        except ImportError:
            local_config = None

        client_id = os.environ.get("TASTY_CLIENT_ID") or getattr(local_config, "CLIENT_ID", None)
        client_secret = os.environ.get("TASTY_CLIENT_SECRET") or getattr(
            local_config, "CLIENT_SECRET", None
        )
        refresh_token = os.environ.get("TASTY_REFRESH_TOKEN") or getattr(
            local_config, "REFRESH_TOKEN", None
        )

        if not client_secret or not refresh_token:
            raise ValueError(
                "No credentials found. Set TASTY_CLIENT_SECRET/TASTY_REFRESH_TOKEN "
                "env vars, or fill in config.py."
            )

        return cls(
            client_secret=client_secret,
            refresh_token=refresh_token,
            client_id=client_id,
            base_url=base_url,
            timeout=timeout,
            print_json=print_json,
        )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _refresh_access_token(self) -> None:
        url = f"{self.base_url}{OAUTH_TOKEN_PATH}"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_secret": self.client_secret,
        }
        if self.client_id:
            payload["client_id"] = self.client_id

        response = self.session.post(url, data=payload, timeout=self.timeout)
        self._raise_for_status(response)

        data = response.json()
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 900)  # seconds; Tastytrade default is 15 min
        # Refresh a little early to avoid edge-of-expiry failures.
        self._access_token_expires_at = time.time() + max(expires_in - 30, 0)

    def _ensure_access_token(self) -> str:
        if self._access_token is None or time.time() >= self._access_token_expires_at:
            self._refresh_access_token()
        return self._access_token

    # ------------------------------------------------------------------
    # Core request plumbing
    # ------------------------------------------------------------------

    def _raise_for_status(self, response: requests.Response) -> None:
        if response.ok:
            return
        try:
            payload = response.json()
        except ValueError:
            payload = None

        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = error.get("message", response.text)
        elif isinstance(error, str):
            message = error
        else:
            message = response.text

        raise TastytradeAPIError(response.status_code, message, payload)

    def request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        retry_on_auth_failure: bool = True,
    ) -> Any:
        """Make an authenticated request against the Tastytrade API.

        `path` should start with '/' e.g. '/accounts'.
        Returns the parsed JSON body (or None for 204 responses).
        """
        token = self._ensure_access_token()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        response = self.session.request(
            method,
            url,
            params=params,
            json=json,
            headers=headers,
            timeout=self.timeout,
        )

        if response.status_code == 401 and retry_on_auth_failure:
            # Access token may have been revoked/expired out of band; force one retry.
            self._access_token = None
            return self.request(method, path, params=params, json=json, retry_on_auth_failure=False)

        self._raise_for_status(response)

        if response.status_code == 204 or not response.content:
            return None

        data = response.json()
        if self.print_json:
            print(_json.dumps(data, indent=2))
        return data

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        return self.request("POST", path, params=params, json=json)

    def put(self, path: str, json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        return self.request("PUT", path, params=params, json=json)

    def delete(self, path: str, params: Optional[dict] = None) -> Any:
        return self.request("DELETE", path, params=params)

    # ------------------------------------------------------------------
    # Convenience wrappers for common endpoints
    # ------------------------------------------------------------------

    def get_customer(self) -> dict:
        return self.get("/customers/me")["data"]

    def get_accounts(self) -> list[dict]:
        return self.get("/customers/me/accounts")["data"]["items"]

    def get_balances(self, account_number: str) -> dict:
        return self.get(f"/accounts/{account_number}/balances")["data"]

    def get_positions(self, account_number: str) -> list[dict]:
        return self.get(f"/accounts/{account_number}/positions")["data"]["items"]

    def get_orders(self, account_number: str, **filters: Any) -> list[dict]:
        return self.get(f"/accounts/{account_number}/orders", params=filters)["data"]["items"]

    def place_order(self, account_number: str, order: dict, dry_run: bool = False) -> dict:
        path = f"/accounts/{account_number}/orders"
        if dry_run:
            path += "/dry-run"
        return self.post(path, json=order)["data"]

    def cancel_order(self, account_number: str, order_id: str) -> dict:
        return self.delete(f"/accounts/{account_number}/orders/{order_id}")

    def get_quote(self, symbol: str) -> dict:
        """NOTE: unverified — /market-data/quotes/{symbol} returned 400/404 in
        testing. Tastytrade does not appear to expose snapshot quotes over
        plain REST; real-time quotes require the DXLink WebSocket streamer
        (see get_quote_token())."""
        return self.get(f"/market-data/quotes/{symbol}")["data"]

    def get_quote_token(self) -> dict:
        """Fetch a DXLink streamer token (dxlink-url + token) for subscribing
        to real-time quotes over WebSocket. Confirmed working via /api-quote-tokens.
        This client only fetches the token — it does not implement the DXLink
        WebSocket protocol itself."""
        return self.get("/api-quote-tokens")["data"]

    def get_option_chain(self, symbol: str) -> list[dict]:
        return self.get(f"/option-chains/{symbol}")["data"]["items"]

    def get_future_option_chain(
        self,
        symbol: str,
        expiration_date: Optional[str] = None,
        option_type: Optional[str] = None,
        strike_price: Optional[float] = None,
        min_dte: Optional[int] = None,
        max_dte: Optional[int] = None,
        nested: bool = False,
    ) -> list[dict]:
        """List future-option contracts for a futures product, e.g. '/ES' or 'ES'.

        Optional filters (applied client-side, since the endpoint itself
        returns the full contract list):
          expiration_date: exact match, e.g. '2026-12-18'
          option_type: 'C'/'Call' or 'P'/'Put'
          strike_price: exact strike match
          min_dte / max_dte: inclusive days-to-expiration bounds
          nested: use the '/nested' variant, grouped by underlying future
                  expiration ({"futures": [...], "option-chains": [...]});
                  filters above are ignored for this shape
        """
        root_symbol = symbol.lstrip("/")
        path = f"/futures-option-chains/{root_symbol}"
        if nested:
            data = self.get(path + "/nested")["data"]
            return data["option-chains"]

        items = self.get(path)["data"]["items"]

        if expiration_date is not None:
            items = [i for i in items if i.get("expiration-date") == expiration_date]
        if option_type is not None:
            wanted = option_type[0].upper()  # 'C' or 'P'
            items = [i for i in items if i.get("option-type", "").upper().startswith(wanted)]
        if strike_price is not None:
            items = [i for i in items if float(i.get("strike-price", 0)) == float(strike_price)]
        if min_dte is not None:
            items = [i for i in items if i.get("days-to-expiration", 0) >= min_dte]
        if max_dte is not None:
            items = [i for i in items if i.get("days-to-expiration", 0) <= max_dte]

        return items

    def get_equity(self, symbol: str) -> dict:
        return self.get(f"/instruments/equities/{symbol}")["data"]

    def get_future(self, symbol: str) -> dict:
        """Look up a single, specific futures contract, e.g. 'ESZ6' or
        '/ESZ6' (leading '/' is stripped). For the list of live contracts
        under a root symbol, use get_futures_by_product_code()."""
        return self.get(f"/instruments/futures/{symbol.lstrip('/')}")["data"]

    def get_futures_by_product_code(self, product_code: str) -> list[dict]:
        """List live futures contracts for a root symbol, e.g. 'ES' or '/ES'."""
        product_code = product_code.lstrip("/")
        return self.get("/instruments/futures", params={"product-code[]": product_code})["data"]["items"]

    def get_live_underlying_price(self, ticker: str, timeout: float = 5.0) -> float:
        """Fetch a live price for `ticker` itself (equity ticker or futures
        root, e.g. '/ES') over DXLink — not an option contract.

        Resolves the underlying's real dxFeed streamer symbol via the
        instruments API (for a futures root, the active-month contract;
        Tastytrade computes the correct exchange-qualified symbol, so this
        doesn't guess at the format). Opens a short-lived DXLinkStreamer,
        races a Trade subscription against a Quote subscription, and
        returns whichever arrives first: the last trade price, or the
        bid/ask midpoint if no trade shows up within `timeout` seconds.

        Raises TimeoutError if neither arrives in time (e.g. market
        closed, no streaming entitlement, or an illiquid symbol).
        """
        from .dxlink_streamer import DXLinkStreamer  # lazy: only needed here

        if ticker.strip().startswith("/"):
            contracts = self.get_futures_by_product_code(ticker)
            if not contracts:
                raise ValueError(f"No live futures contracts found for {ticker!r}")
            front = next((c for c in contracts if c.get("active-month")), contracts[0])
            streamer_symbol = front["streamer-symbol"]
        else:
            streamer_symbol = self.get_equity(ticker)["streamer-symbol"]

        quote_token = self.get_quote_token()

        async def _fetch() -> float:
            async with DXLinkStreamer(quote_token) as streamer:
                await streamer.subscribe("Trade", streamer_symbol)
                await streamer.subscribe("Quote", streamer_symbol)

                trade_task = asyncio.ensure_future(streamer.get_event("Trade"))
                quote_task = asyncio.ensure_future(streamer.get_event("Quote"))
                done, pending = await asyncio.wait(
                    {trade_task, quote_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()

                if trade_task in done:
                    return float(trade_task.result()["price"])
                if quote_task in done:
                    quote = quote_task.result()
                    return (float(quote["bidPrice"]) + float(quote["askPrice"])) / 2
                raise TimeoutError(f"No live price received for {ticker!r} within {timeout}s")

        return asyncio.run(_fetch())

    def get_chain_quotes(self, chain: list[dict], timeout: float = 5.0) -> dict[str, dict]:
        """Fetch live bid/ask for every contract in an options chain (as
        returned by get_options_chain() / get_option_chain() /
        get_future_option_chain()) over DXLink, in a single streaming
        session — the REST chain endpoints only return contract metadata,
        not pricing.

        Returns {streamer_symbol: {"bid": float, "ask": float}}. Contracts
        that don't produce a Quote within `timeout` seconds are simply
        omitted from the result (illiquid strikes may have no live quote)
        rather than raising — check the chain length against the result
        length if you need to know what's missing.

        Subscribing to hundreds of contracts at once (e.g. an unfiltered
        chain) works but is slow and noisy — filter with get_options_chain()
        first (num_strikes, dte, option_type) before calling this.
        """
        symbols = [c["streamer-symbol"] for c in chain if c.get("streamer-symbol")]
        if not symbols:
            return {}

        quote_token = self.get_quote_token()

        async def _fetch() -> dict[str, dict]:
            from .dxlink_streamer import DXLinkStreamer  # lazy: only needed here

            results: dict[str, dict] = {}
            remaining = set(symbols)

            async def _collect() -> None:
                while remaining:
                    quote = await streamer.get_event("Quote")
                    sym = quote["eventSymbol"]
                    if sym in remaining:
                        results[sym] = {"bid": float(quote["bidPrice"]), "ask": float(quote["askPrice"])}
                        remaining.discard(sym)

            async with DXLinkStreamer(quote_token) as streamer:
                await streamer.subscribe("Quote", symbols)
                try:
                    await asyncio.wait_for(_collect(), timeout=timeout)
                except asyncio.TimeoutError:
                    pass
            return results

        return asyncio.run(_fetch())

    def get_chain_greeks(self, chain: list[dict], timeout: float = 5.0) -> dict[str, dict]:
        """Fetch live greeks (delta, gamma, theta, rho, vega) and IV for every
        contract in an options chain (as returned by get_options_chain() /
        get_option_chain() / get_future_option_chain()) over DXLink's
        'Greeks' event — Tastytrade doesn't expose an ITM-probability field
        directly; |delta| is the standard proxy for it.

        Returns {streamer_symbol: {"delta": float, "gamma": float,
        "theta": float, "rho": float, "vega": float, "iv": float}}.
        Contracts that don't produce a Greeks event within `timeout` seconds
        are simply omitted from the result (illiquid strikes may have no
        live greeks) rather than raising.

        Subscribing to hundreds of contracts at once (e.g. an unfiltered
        chain) works but is slow and noisy — filter with get_options_chain()
        first (num_strikes, dte, option_type) before calling this.
        """
        symbols = [c["streamer-symbol"] for c in chain if c.get("streamer-symbol")]
        if not symbols:
            return {}

        quote_token = self.get_quote_token()

        async def _fetch() -> dict[str, dict]:
            from .dxlink_streamer import DXLinkStreamer  # lazy: only needed here

            results: dict[str, dict] = {}
            remaining = set(symbols)

            async def _collect() -> None:
                while remaining:
                    greeks = await streamer.get_event("Greeks")
                    sym = greeks["eventSymbol"]
                    if sym in remaining:
                        results[sym] = {
                            "delta": float(greeks["delta"]),
                            "gamma": float(greeks["gamma"]),
                            "theta": float(greeks["theta"]),
                            "rho": float(greeks["rho"]),
                            "vega": float(greeks["vega"]),
                            "iv": float(greeks["volatility"]),
                        }
                        remaining.discard(sym)

            async with DXLinkStreamer(quote_token) as streamer:
                await streamer.subscribe("Greeks", symbols)
                try:
                    await asyncio.wait_for(_collect(), timeout=timeout)
                except asyncio.TimeoutError:
                    pass
            return results

        return asyncio.run(_fetch())

    def get_options_chain(
        self,
        ticker: str,
        dte: Optional[int] = None,
        min_dte: Optional[int] = None,
        max_dte: Optional[int] = None,
        expiration_date: Optional[str] = None,
        option_type: str = "all",
        num_strikes: Optional[int] = None,
        underlying_price: Optional[float] = None,
        fetch_live_price: bool = True,
        price_timeout: float = 5.0,
    ) -> list[dict]:
        """Pull and filter an options chain for an equity ticker (e.g.
        'AAPL') or a futures root (e.g. '/ES') — futures are detected by a
        leading '/' and routed to get_future_option_chain(); everything
        else goes through get_option_chain(). Both return Tastytrade's
        native contract-dict shape, so filters below work identically for
        either.

        Filters apply in this order:
          1. option_type: 'call'/'put'/'all' (default 'all').
          2. expiration — at most one of:
               expiration_date  exact 'YYYY-MM-DD' match
               dte              nearest available expiration to this many
                                 days out (not an exact match — options
                                 don't expire on arbitrary days)
               min_dte/max_dte  inclusive days-to-expiration range
             Omit all three to keep every expiration.
          3. num_strikes — keep only the N strikes closest to
             underlying_price, applied independently within each
             remaining expiration (so "10 strikes" means 10 per
             expiration, not 10 total across several).

             If underlying_price isn't given and fetch_live_price is True
             (default), it's fetched over DXLink via
             get_live_underlying_price() — this makes the call block for
             up to price_timeout seconds and open a WebSocket connection.
             If that fetch fails (market closed, no streaming entitlement,
             network issue) or fetch_live_price=False, this falls back to
             the median remaining strike as a rough ATM proxy and emits a
             RuntimeWarning; pass underlying_price explicitly to skip all
             of this and center on a price you already have.

        Returns contracts sorted by (expiration, strike, option type).
        """
        is_future = ticker.strip().startswith("/")
        items = self.get_future_option_chain(ticker) if is_future else self.get_option_chain(ticker)

        option_type = (option_type or "all").strip().lower()
        if option_type not in ("all", "call", "calls", "c", "put", "puts", "p"):
            raise ValueError(f"option_type must be 'call', 'put', or 'all', got {option_type!r}")
        if option_type != "all":
            wanted = "P" if option_type.startswith("p") else "C"
            items = [i for i in items if i.get("option-type", "").upper().startswith(wanted)]

        if expiration_date is not None:
            items = [i for i in items if i.get("expiration-date") == expiration_date]
        elif dte is not None:
            available = {i["days-to-expiration"] for i in items if i.get("days-to-expiration") is not None}
            if available:
                closest = min(available, key=lambda d: abs(d - dte))
                items = [i for i in items if i.get("days-to-expiration") == closest]
        else:
            if min_dte is not None:
                items = [i for i in items if i.get("days-to-expiration", 0) >= min_dte]
            if max_dte is not None:
                items = [i for i in items if i.get("days-to-expiration", 0) <= max_dte]

        if num_strikes is not None:
            if underlying_price is None and fetch_live_price:
                try:
                    underlying_price = self.get_live_underlying_price(ticker, timeout=price_timeout)
                except Exception as exc:
                    warnings.warn(
                        f"Couldn't fetch a live price for {ticker!r} ({exc}); falling back to "
                        "the median remaining strike as an ATM proxy.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
            items = self._nearest_strikes(items, num_strikes, underlying_price)

        return sorted(
            items,
            key=lambda i: (i.get("expiration-date", ""), float(i.get("strike-price", 0)), i.get("option-type", "")),
        )

    @staticmethod
    def _nearest_strikes(items: list[dict], num_strikes: int, underlying_price: Optional[float]) -> list[dict]:
        """Keep, per expiration, only the num_strikes contracts whose
        strike is closest to underlying_price (or the median strike, if
        no price was given)."""
        if num_strikes <= 0:
            raise ValueError("num_strikes must be positive")

        by_expiration: dict[str, list[dict]] = {}
        for item in items:
            by_expiration.setdefault(item.get("expiration-date", ""), []).append(item)

        selected: list[dict] = []
        for exp_items in by_expiration.values():
            strikes = sorted({float(i["strike-price"]) for i in exp_items})
            if not strikes:
                continue
            reference = underlying_price if underlying_price is not None else strikes[len(strikes) // 2]
            closest = set(sorted(strikes, key=lambda s: abs(s - reference))[:num_strikes])
            selected.extend(i for i in exp_items if float(i["strike-price"]) in closest)

        return selected

    def get_future_option_quote(self, symbols: str | list[str]) -> list[dict]:
        """NOTE: unverified — /market-data/quotes returned 404 in testing
        against production. See get_quote()/get_quote_token() for details;
        real-time quotes likely require the DXLink WebSocket streamer instead.

        Symbols use Tastytrade's future-option format, e.g. './ESZ4 EW4U4 240920P4700'
        (obtainable from get_future_option_chain).
        """
        if isinstance(symbols, str):
            symbols = [symbols]
        return self.get("/market-data/quotes", params={"future-option[]": symbols})["data"]["items"]

