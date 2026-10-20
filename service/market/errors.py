"""How Market failures surface. Two cases, never confused with each other
or with "nothing matched":

  SymbolNotFound    the symbol doesn't exist or has nothing listed -> 404
  MarketDataError   Tastytrade/DXLink failed (error, timeout, dropped
                    stream) -> 502, with a fixed user-facing message; the
                    real cause is logged, never sent to the browser.

translate_errors() is the one place broker exceptions become these.
"""

import logging
from contextlib import contextmanager

from broker.tastytrade import TastytradeAPIError

logger = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = "Market data is temporarily unavailable. Please try again shortly."


class SymbolNotFound(LookupError):
    def __init__(self, symbol: str, what: str = "market data"):
        self.symbol = symbol
        super().__init__(f"No {what} found for {symbol}")


class MarketDataError(Exception):
    def __init__(self, message: str = UNAVAILABLE_MESSAGE):
        super().__init__(message)


@contextmanager
def translate_errors(symbol: str, action: str):
    """Map anything the Tastytrade client raises inside the block to
    SymbolNotFound / MarketDataError, logging the real cause."""
    try:
        yield
    except (SymbolNotFound, MarketDataError):
        raise
    except TastytradeAPIError as e:
        if e.status_code == 404:
            raise SymbolNotFound(symbol) from e
        logger.error("%s for %s failed: %s", action, symbol, e)
        raise MarketDataError() from e
    except Exception as e:  # timeouts, DXLink/WebSocket errors, unexpected payloads
        logger.exception("%s for %s failed: %s", action, symbol, e)
        raise MarketDataError() from e
