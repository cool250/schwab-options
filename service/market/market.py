"""MarketService: the one entry point the API and the copilot use for
market data. Each feature lives in its own module — chains
(chain_providers.py), price history (history.py), the Screener
(screener.py), the Strategy Builder solver (strategy_builder.py) — and this
class wires them to the chain provider and the shared Tastytrade client.
Building a strategy is here because it orchestrates chain fetches.

Failures surface as SymbolNotFound / MarketDataError (errors.py); None
means "nothing listed / no data".
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from broker.tastytrade import TastytradeClient, get_shared_client
from service.market import history, screener, strategy_builder
from service.market.chain_providers import OptionChainProvider, get_option_chain_provider
from service.market.errors import MarketDataError, SymbolNotFound

logger = logging.getLogger(__name__)


def normalize_symbol(symbol: str) -> str:
    """'spy ' -> 'SPY', '/es' -> '/ES'. The API validates the format too;
    this keeps every cache and lookup keyed one way for other callers."""
    return symbol.strip().upper()


class MarketService:
    def __init__(self, chain_provider: Optional[OptionChainProvider] = None, client: Optional[TastytradeClient] = None):
        # Both injectable for tests; otherwise the shared ones, built lazily.
        self._chain_provider = chain_provider
        self._client = client

    @property
    def option_chain_provider(self) -> OptionChainProvider:
        if self._chain_provider is None:
            self._chain_provider = get_option_chain_provider()
        return self._chain_provider

    def _get_client(self) -> TastytradeClient:
        if self._client is None:
            try:
                self._client = get_shared_client()
            except ValueError as e:  # credentials not configured
                logger.error("Tastytrade client unavailable: %s", e)
                raise MarketDataError() from e
        return self._client

    # --- Charts ---

    def get_price_history(self, symbol: str, range_key: str = history.DEFAULT_RANGE) -> Optional[dict]:
        """See history.get_price_history."""
        return history.get_price_history(self._get_client(), normalize_symbol(symbol), range_key)

    # --- Chains ---

    def get_expirations(self, symbol: str, days_ahead: int = 60) -> list[dict]:
        """Every expiration listed for `symbol` within `days_ahead` days —
        weekly, monthly and daily where offered: [{"date", "dte"}] by dte."""
        return self.option_chain_provider.get_expirations(normalize_symbol(symbol), days_ahead)

    def get_option_chain(
        self, symbol: str, dte: Optional[int] = None, strike_count: int = 20, expiration_date: Optional[str] = None
    ) -> Optional[dict]:
        """One expiration's chain: exactly `expiration_date` when given,
        else the listing closest to `dte` (see OptionChainProvider)."""
        return self.option_chain_provider.get_option_chain(
            normalize_symbol(symbol), dte, strike_count, expiration_date
        )

    # --- Screener ---

    def screen_options(self, symbols: list[str], *args, **kwargs) -> dict:
        """See screener.screen_options."""
        return screener.screen_options(self.option_chain_provider, [normalize_symbol(s) for s in symbols], *args, **kwargs)

    # --- Strategy Builder ---

    def get_strategy_templates(self) -> list[dict]:
        """Strategy Builder templates — the one definition the Analyze
        page's builder form is generated from."""
        return strategy_builder.list_templates()

    def build_strategy(
        self,
        symbol: str,
        dte: int,
        strategy: str,
        params: dict,
        target: Optional[float] = None,
        expiration_date: Optional[str] = None,
        max_dte: Optional[int] = None,
    ) -> Optional[dict]:
        """Place `strategy`'s legs on the live chain, priced at mid — see
        strategy_builder.build for the solver, `params` and `target`.

        On exactly `expiration_date` when given (else the listing closest to
        `dte`). With `max_dte` > `dte`, builds on every listed expiration in
        [dte, max_dte] instead (at most MAX_RANGE_EXPIRATIONS) and ranks them
        together; every candidate carries its own expirationDate/dte, and the
        top-level ones are the best's.

        Returns None if nothing is listed. Raises StrategyParamError (-> 422)
        for bad parameters, SymbolNotFound / MarketDataError otherwise.
        """
        symbol = normalize_symbol(symbol)
        if max_dte is not None and max_dte > dte:
            return self._build_strategy_range(symbol, dte, max_dte, strategy, params, target)
        strategy_builder.resolve_params(strategy, params, target)  # fail fast, before any fetch
        chain = self.option_chain_provider.get_option_chain(
            symbol, dte, strategy_builder.STRIKE_COUNT, expiration_date
        )
        if chain is None:
            return None
        return self._build_result(symbol, strategy, chain, strategy_builder.build(strategy, params, chain, target), 1)

    def _build_strategy_range(
        self, symbol: str, min_dte: int, max_dte: int, strategy: str, params: dict, target: Optional[float]
    ) -> Optional[dict]:
        strategy_builder.resolve_params(strategy, params, target)  # fail fast, before any fetch
        expirations = [e for e in self.get_expirations(symbol, max_dte) if min_dte <= e["dte"] <= max_dte]
        if not expirations:
            return None
        if len(expirations) > strategy_builder.MAX_RANGE_EXPIRATIONS:
            raise strategy_builder.StrategyParamError(
                f"{len(expirations)} expirations fall in that range — narrow it to at most "
                f"{strategy_builder.MAX_RANGE_EXPIRATIONS}"
            )
        # One spot price for every expiration, then each chain by its exact date.
        spot = self.option_chain_provider.get_spot(symbol)

        def fetch(expiration: dict):
            try:
                return self.option_chain_provider.get_option_chain(
                    symbol, None, strategy_builder.STRIKE_COUNT, expiration["date"], spot=spot
                ), False
            except (MarketDataError, SymbolNotFound):  # one bad expiration shouldn't sink the rest
                return None, True

        with ThreadPoolExecutor(max_workers=min(screener.WORKERS, len(expirations))) as pool:
            fetched = list(pool.map(fetch, expirations))

        failed = [e["date"] for e, (_, error) in zip(expirations, fetched) if error]
        chains = [chain for chain, _ in fetched if chain is not None]
        if not chains:
            if failed:
                raise MarketDataError()
            return None
        combined = strategy_builder.combine(strategy, [strategy_builder.build(strategy, params, c, target) for c in chains])
        if failed:
            combined["reasons"].append(f"Couldn't load {len(failed)} expiration(s): {', '.join(failed)}")
        best = combined["best"]
        lead = next((c for c in chains if best and c.get("expirationDate") == best["expirationDate"]), chains[0])
        return self._build_result(symbol, strategy, lead, combined, len(chains))

    @staticmethod
    def _build_result(symbol: str, strategy: str, chain: dict, result: dict, searched: int) -> dict:
        return {
            "symbol": symbol,
            "strategy": strategy,
            "spot": chain["spot"],
            "iv": chain.get("iv"),
            "dte": chain.get("dte"),
            "expirationDate": chain.get("expirationDate"),
            "expirationsSearched": searched,
            **result,
        }
