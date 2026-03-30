"""
Token provider abstraction for the broker SDK.

The default :class:`EnvTokenProvider` reads tokens from ``token.json``,
the ``TOKEN_JSON`` env var, or Redis (when ``USE_DB=true``).

To use a custom storage backend, subclass :class:`TokenProvider` and pass
an instance to :class:`broker.client.Client`::

    from broker.token_provider import TokenProvider

    class MyProvider(TokenProvider):
        def get_access_token(self) -> str:
            return my_vault.read("schwab_access_token")

        def get_refresh_token(self) -> str:
            return my_vault.read("schwab_refresh_token")

        def save_tokens(self, token_data: dict) -> None:
            my_vault.write("schwab_access_token", token_data["access_token"])
            my_vault.write("schwab_refresh_token", token_data["refresh_token"])

        def get_app_credentials(self) -> tuple[str, str, str]:
            return (
                my_vault.read("schwab_app_key"),
                my_vault.read("schwab_app_secret"),
                my_vault.read("schwab_callback_url"),
            )

    client = Client(token_provider=MyProvider())
"""

from abc import ABC, abstractmethod


class TokenProvider(ABC):
    """Abstract interface for Schwab OAuth token storage and retrieval."""

    @abstractmethod
    def get_access_token(self) -> str:
        """Return the current Bearer access token."""

    @abstractmethod
    def get_refresh_token(self) -> str:
        """Return the current refresh token."""

    @abstractmethod
    def save_tokens(self, token_data: dict) -> None:
        """
        Persist a token payload after a successful refresh.

        *token_data* is the JSON dict returned by the Schwab token endpoint,
        containing at minimum ``access_token`` and ``refresh_token`` keys.
        """

    @abstractmethod
    def get_app_credentials(self) -> tuple[str, str, str]:
        """
        Return ``(app_key, app_secret, app_callback_url)`` for OAuth flows.

        These are the Schwab developer-portal credentials needed to exchange
        a refresh token for a new access token.
        """


class EnvTokenProvider(TokenProvider):
    """
    Default token provider.

    Reads/writes tokens from ``token.json`` (local file), the ``TOKEN_JSON``
    environment variable, or Redis when ``USE_DB=true``.  App credentials
    are read from the ``APP_KEY``, ``APP_SECRET``, and ``APP_CALLBACK_URL``
    environment variables.
    """

    def get_access_token(self) -> str:
        from utils.read_token import get_access_token as _get
        return _get()

    def get_refresh_token(self) -> str:
        from utils.read_token import get_response_token as _get
        return _get()

    def save_tokens(self, token_data: dict) -> None:
        from utils.read_token import save_token
        save_token(token_data)

    def get_app_credentials(self) -> tuple[str, str, str]:
        from utils.utils import get_app_credentials
        return get_app_credentials()
