"""
Token provider abstraction for the broker SDK.

Concrete implementations:

* :class:`FileTokenProvider` — persists tokens to a local ``token.json`` file.
* :class:`RedisTokenProvider` — persists tokens in Redis (suitable for
  ephemeral/cloud environments with no persistent disk).

The :func:`create_token_provider` factory selects the backend automatically:
it returns :class:`RedisTokenProvider` when the ``USE_DB`` environment variable
is set to a truthy value, and falls back to :class:`FileTokenProvider`
otherwise.

To use a custom storage backend, subclass :class:`TokenProvider` and pass
an instance to :class:`broker.schwab.client.Client`::

    from broker.schwab.auth import TokenProvider

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

import base64
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod

import redis
import requests

logger = logging.getLogger(__name__)

_SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"

# Process-wide token cache, keyed by store (see TokenProvider._cached). Every
# Schwab client builds its own provider instance (BaseClient →
# create_token_provider()), so the cache lives at module level for all of
# them to share; values are (store_version, token_data).
_cache_lock = threading.RLock()
_token_cache: dict[str, tuple[object, dict]] = {}

# Schwab refresh tokens can't be renewed through the API — they last 7 days
# from the interactive login that issued them, after which the user has to
# log in again (main.py locally, or Settings → Reconnect Schwab in the app).
REFRESH_TOKEN_LIFETIME = 7 * 24 * 3600


def get_app_credentials() -> tuple[str, str, str]:
    """Return (app_key, app_secret, app_callback_url) from environment variables."""
    app_key = os.getenv("SCHWAB_APP_KEY")
    app_secret = os.getenv("SCHWAB_APP_SECRET")
    app_callback_url = os.getenv("SCHWAB_APP_CALLBACK_URL")

    if not app_key or not app_secret or not app_callback_url:
        missing = [n for n, v in [("SCHWAB_APP_KEY", app_key), ("SCHWAB_APP_SECRET", app_secret), ("SCHWAB_APP_CALLBACK_URL", app_callback_url)] if not v]
        logger.error("Missing environment variables: %s", missing)
        raise ValueError(f"Environment variables missing: {missing}")

    return app_key, app_secret, app_callback_url

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

    # ─── In-memory cache ─────────────────────────────────────────────
    # Tokens are read from the store once and then served from memory, so a
    # Schwab call doesn't re-read token.json/Redis every time — and can't
    # catch a save half-written. Subclasses identify their store and, where
    # cheap, a version stamp that changes when something *outside* this
    # process rewrites it (e.g. main.py or an sftp upload replacing
    # token.json), which triggers a reload. A provider without a version
    # stamp (None) relies on invalidate_cache(), which BaseClient calls on a
    # 401 before refreshing.

    def _store_id(self) -> str:
        return f"{type(self).__name__}:{id(self)}"

    def _store_version(self) -> object:
        return None

    def _cached(self) -> dict:
        store_id = self._store_id()
        with _cache_lock:
            hit = _token_cache.get(store_id)
            if hit is not None and (hit[0] is None or hit[0] == self._store_version()):
                return hit[1]
            data = self._read()  # type: ignore[attr-defined]
            _token_cache[store_id] = (self._store_version(), data)
            return data

    def _remember(self, data: dict) -> None:
        with _cache_lock:
            _token_cache[self._store_id()] = (self._store_version(), data)

    def invalidate_cache(self) -> None:
        with _cache_lock:
            _token_cache.pop(self._store_id(), None)

    def access_token_expires_soon(self, margin: float = 60) -> bool:
        """True if the stored access token expires within `margin` seconds,
        so BaseClient can refresh it *before* a request instead of after a
        401. False when the expiry is unknown (an older token without
        ``expires_at``) — the 401 path still covers that."""
        try:
            expires_at = self._cached().get("expires_at")
        except Exception:
            return False
        return expires_at is not None and expires_at - margin <= time.time()

    def _stamped(self, token_data: dict) -> dict:
        """_with_expiry plus ``refresh_token_issued_at`` — when Schwab issued
        this refresh token, which sets when it dies (REFRESH_TOKEN_LIFETIME).

        Every 30-minute access-token refresh returns the *same* refresh token,
        so its issue time is carried over from what's stored; only a genuinely
        new refresh token (a fresh login) gets stamped with now. A token saved
        before this tracking existed has no recorded issue time, which stays
        unknown (None) rather than being guessed."""
        try:
            previous = self._cached()
        except Exception:
            previous = None
        if previous and previous.get("refresh_token") == token_data.get("refresh_token"):
            issued_at = previous.get("refresh_token_issued_at")
        else:
            issued_at = time.time()
        return {**self._with_expiry(token_data), "refresh_token_issued_at": issued_at}

    def refresh_token_expires_at(self) -> float | None:
        """Unix time the stored refresh token expires, or None if unknown
        (no token stored, or saved before issue times were tracked)."""
        try:
            issued_at = self._cached().get("refresh_token_issued_at")
        except Exception:
            return None
        return issued_at + REFRESH_TOKEN_LIFETIME if issued_at else None

    def has_tokens(self) -> bool:
        try:
            return bool(self._cached().get("refresh_token"))
        except Exception:
            return False

    def refresh_tokens(self) -> None:
        """Exchange the stored refresh token for a new access/refresh token pair."""
        app_key, app_secret, _ = self.get_app_credentials()
        refresh_token_value = self.get_refresh_token()

        response = requests.post(
            _SCHWAB_TOKEN_URL,
            headers={
                "Authorization": f"Basic {base64.b64encode(f'{app_key}:{app_secret}'.encode()).decode()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token_value},
        )

        if response.status_code != 200:
            logger.error("Error refreshing access token: %s", response.text)
            raise RuntimeError(f"Token refresh failed ({response.status_code}): {response.text}")

        token_data = response.json()
        logger.debug(token_data)
        self.save_tokens(token_data)
        logger.info("Tokens refreshed successfully.")


class FileTokenProvider(TokenProvider):
    """
    Token provider backed by a local JSON file.

    Reads and writes tokens from/to *file_path* — defaults to the
    ``TOKEN_FILE`` env var if set (e.g. ``/data/token.json`` on a Fly.io
    volume, so the token survives restarts/redeploys), otherwise
    ``token.json`` in the working directory (the project root locally).
    """
    _DEFAULT_TOKEN_FILE = "token.json"

    def __init__(
        self,
        file_path: str | None = None,
        app_key: str | None = None,
        app_secret: str | None = None,
        callback_url: str | None = None,
    ) -> None:
        self._file_path = file_path or os.getenv("TOKEN_FILE") or self._DEFAULT_TOKEN_FILE
        self._credentials: tuple[str, str, str] | None = (
            (app_key, app_secret, callback_url)  # type: ignore[assignment]
            if app_key and app_secret and callback_url
            else None
        )

    def _read(self) -> dict:
        with open(self._file_path, "r") as f:
            return json.load(f)

    def _store_id(self) -> str:
        return f"file:{os.path.abspath(self._file_path)}"

    def _store_version(self) -> object:
        # mtime changes whenever the file is replaced — by this process
        # (save_tokens, which records the new mtime) or by anything else.
        try:
            return os.stat(self._file_path).st_mtime_ns
        except OSError:
            return -1  # missing: never matches a cached version, so the read below raises

    def get_access_token(self) -> str:
        return self._cached().get("access_token", "")

    def get_refresh_token(self) -> str:
        return self._cached().get("refresh_token", "")

    def save_tokens(self, token_data: dict) -> None:
        stamped = self._stamped(token_data)
        # Atomic replace: write a temp file, then swap it in, so a reader in
        # another process (or this one, on a cache miss) only ever sees the
        # old or the new file — never a truncated, half-written one. 0600:
        # the file grants access to the brokerage account.
        tmp_path = f"{self._file_path}.tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(stamped, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self._file_path)
        self._remember(stamped)
        logger.debug("Tokens saved to %s", self._file_path)

    def get_app_credentials(self) -> tuple[str, str, str]:
        return self._credentials or get_app_credentials()


class RedisTokenProvider(TokenProvider):
    """
    Token provider backed by Redis.

    Suitable for cloud/ephemeral environments where the local
    filesystem is not durable.  Reads the Redis URL from the ``REDIS_URL``
    environment variable (defaults to ``redis://localhost:6379``).

    Tokens are stored with an ``expires_at`` unix timestamp derived from
    ``expires_in``.  When the stored token has expired, ``TOKEN_JSON`` env var
    is used to re-seed Redis.
    """

    _REDIS_TOKEN_KEY = "TOKEN_JSON"

    def __init__(
        self,
        redis_url: str | None = None,
        app_key: str | None = None,
        app_secret: str | None = None,
        callback_url: str | None = None,
    ) -> None:
        url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        if url.startswith("rediss://"):
            # Managed Redis over TLS (rediss://) often uses self-signed certs; skip verification.
            self._redis = redis.from_url(url, decode_responses=True, ssl_cert_reqs="none")
        else:
            self._redis = redis.from_url(url, decode_responses=True)
        self._credentials: tuple[str, str, str] | None = (
            (app_key, app_secret, callback_url)  # type: ignore[assignment]
            if app_key and app_secret and callback_url
            else None
        )

    def _read(self) -> dict:
        raw = self._redis.get(self._REDIS_TOKEN_KEY)
        if raw:
            data = json.loads(str(raw))
            if time.time() < data.get("expires_at", 0):
                return data
            # Token has expired — fall back to TOKEN_JSON env var.
            logger.info("Redis token has expired; re-seeding from TOKEN_JSON env var.")
        env_token = os.getenv("TOKEN_JSON")
        if env_token:
            data = json.loads(env_token)
            self._redis.set(self._REDIS_TOKEN_KEY, json.dumps(self._with_expiry(data)))
            return data
        raise ValueError("Token not found in Redis and TOKEN_JSON env var is not set.")

    def _store_id(self) -> str:
        return f"redis:{self._REDIS_TOKEN_KEY}"

    def get_access_token(self) -> str:
        return self._cached().get("access_token", "")

    def get_refresh_token(self) -> str:
        return self._cached().get("refresh_token", "")

    def save_tokens(self, token_data: dict) -> None:
        stamped = self._stamped(token_data)
        self._redis.set(self._REDIS_TOKEN_KEY, json.dumps(stamped))
        self._remember(stamped)
        logger.debug("Tokens saved to Redis key '%s'", self._REDIS_TOKEN_KEY)

    def get_app_credentials(self) -> tuple[str, str, str]:
        return self._credentials or get_app_credentials()


def create_token_provider() -> TokenProvider:
    """
    Factory that returns the appropriate :class:`TokenProvider` based on env vars.

    Returns :class:`RedisTokenProvider` when ``USE_DB`` is set to a truthy value
    (``1``, ``true``, or ``yes``); otherwise returns :class:`FileTokenProvider`.
    """
    use_db = os.getenv("USE_DB", "").lower() in ("1", "true", "yes")
    provider = RedisTokenProvider() if use_db else FileTokenProvider()
    logger.debug("Token provider: %s", type(provider).__name__)
    return provider
