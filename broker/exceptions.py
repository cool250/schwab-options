"""
Broker-neutral exception hierarchy, shared across every broker SDK
(broker/schwab, broker/tastytrade, and any future broker).

All broker exceptions inherit from :class:`BrokerError` so callers can
catch the base class without caring which broker raised it::

    from broker.exceptions import BrokerError, BrokerAuthError, BrokerAPIError, BrokerValidationError

    try:
        positions = provider.get_account_snapshot()
    except BrokerAuthError:
        # Token expired and refresh failed — re-authenticate
        ...
    except BrokerAPIError as e:
        print(e.status_code)   # HTTP status, if available
    except BrokerValidationError:
        # API response schema changed
        ...
    except BrokerError:
        # Catch-all for any other broker failure
        ...

broker/schwab/exceptions.py re-exports these (same classes, same identity)
for backward compatibility with existing `from broker.schwab.exceptions
import ...` call sites.
"""


class BrokerError(Exception):
    """Base class for all broker SDK exceptions."""


class BrokerAuthError(BrokerError):
    """
    Raised when authentication fails or a token refresh cannot be completed.

    This typically means the refresh token has expired and the user must
    re-authenticate with the broker.
    """


class BrokerAPIError(BrokerError):
    """
    Raised when an API call returns a non-200 response after all retries.

    Attributes
    ----------
    status_code : int | None
        HTTP status code of the final failed response, if available.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BrokerValidationError(BrokerError):
    """
    Raised when an API response cannot be parsed into the expected model.

    Usually indicates the broker's API schema has changed.
    """
