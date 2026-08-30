"""
Schwab broker SDK.

Typical usage::

    from broker.schwab import Client

    client = Client()
    quote = client.get_price("AAPL")

All public types are re-exported here so callers never need to reach into
sub-modules::

    from broker.schwab import (
        Client,
        TokenProvider, create_token_provider,
        BrokerError, BrokerAuthError, BrokerAPIError, BrokerValidationError,
        StockQuotes, PriceHistoryResponse, OptionChainResponse,
        SecuritiesAccount, Activity,
    )
"""

from .client import Client
from .auth import TokenProvider, create_token_provider
from .exceptions import BrokerError, BrokerAuthError, BrokerAPIError, BrokerValidationError

# Response models — re-exported so callers can type-hint without importing from data/
from .data.account_data import SecuritiesAccount, Activity
from .data.market_data import StockQuotes, PriceHistoryResponse
from .data.option_data import OptionChainResponse

__all__ = [
    # Entry point
    "Client",
    # Token providers
    "TokenProvider",
    "create_token_provider",
    # Exceptions
    "BrokerError",
    "BrokerAuthError",
    "BrokerAPIError",
    "BrokerValidationError",
    # Response models
    "SecuritiesAccount",
    "Activity",
    "StockQuotes",
    "PriceHistoryResponse",
    "OptionChainResponse",
]
