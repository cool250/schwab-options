import logging

from service.option_chain_providers import get_option_chain_provider

logger = logging.getLogger(__name__)


class MarketService:
    def __init__(self):
        self.option_chain_provider = get_option_chain_provider()

    def get_expirations(self, symbol: str, days_ahead: int = 60):
        """
        List every expiration date actually listed for `symbol` within the next
        `days_ahead` days — weekly, monthly, and daily where the underlying
        offers them — rather than guessing at weekly Fridays client-side.
        Backed by whichever broker BROKER_PROVIDER selects (see
        service/option_chain_providers.py).

        Returns:
            list[dict]: [{"date": "YYYY-MM-DD", "dte": int}, ...] sorted by dte.
        """
        return self.option_chain_provider.get_expirations(symbol, days_ahead)

    def get_option_chain(self, symbol: str, dte: int, strike_count: int = 20):
        """
        Fetch a normalized option chain (calls + puts merged by strike) for
        the expiration closest to `dte` days out. Backed by whichever broker
        BROKER_PROVIDER selects (see service/option_chain_providers.py).

        Parameters:
            symbol (str): The ticker symbol for the underlying asset.
            dte (int): Target days-to-expiration.
            strike_count (int): Number of strikes above/below ATM to fetch.

        Returns:
            dict | None: Normalized chain, or None if unavailable.
        """
        return self.option_chain_provider.get_option_chain(symbol, dte, strike_count)
