"""
Token provider abstraction for the broker SDK.

Concrete implementations:

* :class:`FileTokenProvider` — persists tokens to a local ``token.json`` file.
* :class:`RedisTokenProvider` — persists tokens in Redis (suitable for
  ephemeral/cloud environments such as Heroku).

The default :class:`EnvTokenProvider` selects the backend automatically:
it uses :class:`RedisTokenProvider` when the ``USE_DB`` environment variable
is set to a truthy value, and falls back to :class:`FileTokenProvider`
otherwise.

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

import json
import logging
import os
import time
from abc import ABC, abstractmethod

import redis

from utils.utils import TOKEN_FILE_PATH, get_app_credentials

logger = logging.getLogger(__name__)

_REDIS_TOKEN_KEY = "TOKEN_JSON"


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

    def _with_expiry(self, token_data: dict) -> dict:
        return {**token_data, "expires_at": time.time() + token_data.get("expires_in", 1800)}


class FileTokenProvider(TokenProvider):
    """
    Token provider backed by a local JSON file.

    Reads and writes tokens from/to *file_path* (defaults to ``token.json``
    in the project root).
    """

    def __init__(self, file_path: str = TOKEN_FILE_PATH) -> None:
        self._file_path = file_path

    def _read(self) -> dict:
        with open(self._file_path, "r") as f:
            return json.load(f)

    def get_access_token(self) -> str:
        token = self._read().get("access_token", "")
        logger.debug("access_token read from file")
        return token

    def get_refresh_token(self) -> str:
        token = self._read().get("refresh_token", "")
        logger.debug("refresh_token read from file")
        return token

    def save_tokens(self, token_data: dict) -> None:
        with open(self._file_path, "w") as f:
            json.dump(self._with_expiry(token_data), f, indent=4)
        logger.debug("Tokens saved to %s", self._file_path)

    def get_app_credentials(self) -> tuple[str, str, str]:
        return get_app_credentials()


class RedisTokenProvider(TokenProvider):
    """
    Token provider backed by Redis.

    Suitable for cloud/ephemeral environments (e.g. Heroku) where the local
    filesystem is not durable.  Reads the Redis URL from the ``REDIS_URL``
    environment variable (defaults to ``redis://localhost:6379``).

    Tokens are stored with an ``expires_at`` unix timestamp derived from
    ``expires_in``.  When the stored token has expired, ``TOKEN_JSON`` env var
    is used to re-seed Redis.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        if url.startswith("rediss://"):
            # Heroku Redis uses TLS; skip cert verification for self-signed certs.
            self._redis = redis.from_url(url, decode_responses=True, ssl_cert_reqs="none")
        else:
            self._redis = redis.from_url(url, decode_responses=True)

    def _read(self) -> dict:
        raw = self._redis.get(_REDIS_TOKEN_KEY)
        if raw:
            data = json.loads(raw)
            if time.time() < data.get("expires_at", 0):
                return data
            # Token has expired — fall back to TOKEN_JSON env var.
            logger.info("Redis token has expired; re-seeding from TOKEN_JSON env var.")
        env_token = os.getenv("TOKEN_JSON")
        if env_token:
            data = json.loads(env_token)
            self._redis.set(_REDIS_TOKEN_KEY, json.dumps(self._with_expiry(data)))
            return data
        raise ValueError("Token not found in Redis and TOKEN_JSON env var is not set.")

    def get_access_token(self) -> str:
        token = self._read().get("access_token", "")
        logger.debug("access_token read from Redis")
        return token

    def get_refresh_token(self) -> str:
        token = self._read().get("refresh_token", "")
        logger.debug("refresh_token read from Redis")
        return token

    def save_tokens(self, token_data: dict) -> None:
        self._redis.set(_REDIS_TOKEN_KEY, json.dumps(self._with_expiry(token_data)))
        logger.debug("Tokens saved to Redis key '%s'", _REDIS_TOKEN_KEY)

    def get_app_credentials(self) -> tuple[str, str, str]:
        return get_app_credentials()


class EnvTokenProvider(TokenProvider):
    """
    Environment-driven token provider.

    Delegates to :class:`RedisTokenProvider` when ``USE_DB`` is set to a
    truthy value (``1``, ``true``, or ``yes``); otherwise delegates to
    :class:`FileTokenProvider`.

    App credentials are read from the ``APP_KEY``, ``APP_SECRET``, and
    ``APP_CALLBACK_URL`` environment variables.
    """

    def __init__(self) -> None:
        use_db = os.getenv("USE_DB", "").lower() in ("1", "true", "yes")
        self._backend: TokenProvider = RedisTokenProvider() if use_db else FileTokenProvider()
        logger.debug(
            "EnvTokenProvider using %s backend", type(self._backend).__name__
        )

    def get_access_token(self) -> str:
        return self._backend.get_access_token()

    def get_refresh_token(self) -> str:
        return self._backend.get_refresh_token()

    def save_tokens(self, token_data: dict) -> None:
        self._backend.save_tokens(token_data)

    def get_app_credentials(self) -> tuple[str, str, str]:
        return self._backend.get_app_credentials()
