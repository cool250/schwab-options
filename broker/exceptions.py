"""
Typed exception hierarchy for the broker SDK.

All broker exceptions inherit from :class:`BrokerError` so callers can
catch the base class when they don't need to distinguish failure modes::

    from broker.exceptions import BrokerError, BrokerAuthError, BrokerAPIError, BrokerValidationError

    try:
        quote = client.get_price("AAPL")
    except BrokerAuthError:
        # Token expired and refresh failed — re-authenticate via broker.auth.authenticate
        ...
    except BrokerAPIError as e:
        print(e.status_code)   # HTTP status, if available
    except BrokerValidationError:
        # API response schema changed
        ...
    except BrokerError:
        # Catch-all for any other broker failure
        ...
"""


class BrokerError(Exception):
    """Base class for all broker SDK exceptions."""


class BrokerAuthError(BrokerError):
    """
    Raised when authentication fails or a token refresh cannot be completed.

    This typically means the refresh token has expired and the user must
    re-authenticate via :func:`broker.auth.authenticate.get_access_token`.
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
    Raised when an API response cannot be parsed into the expected Pydantic model.

    Usually indicates the Schwab API schema has changed.
    """
