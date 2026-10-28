"""
Token provider abstraction for the broker SDK.

Concrete implementation: :class:`FileTokenProvider`, which persists tokens
to a local ``token.json`` file (on Fly, the /data volume). The
:func:`create_token_provider` factory returns one for the current user.

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

import json
import logging
import os
import threading
import time
from contextvars import ContextVar, Token
from typing import Optional
from abc import ABC, abstractmethod

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)

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


# ─── Encryption at rest ─────────────────────────────────────────────────
# With TOKEN_ENCRYPTION_KEY set (a Fly secret, so never on the volume), token
# files are Fernet-encrypted: a copy of the volume — a snapshot, a backup, an
# sftp download — no longer gives access to anyone's brokerage account.
# Several comma-separated keys rotate: the first encrypts, any of them
# decrypts, and the next save (every ~30 min refresh) re-encrypts with the
# first. Without a key (local dev, main.py) files stay plain JSON; a plain
# file found while a key is set is encrypted in place on first read.

class TokenDecryptError(ValueError):
    """The token file can't be decrypted. A ValueError, so BaseClient treats
    it like a missing token: the user is asked to reconnect Schwab, which
    rewrites the file with the current key."""


def _cipher() -> Optional[MultiFernet]:
    keys = [k.strip() for k in os.getenv("TOKEN_ENCRYPTION_KEY", "").split(",") if k.strip()]
    return MultiFernet([Fernet(k) for k in keys]) if keys else None


def check_token_encryption() -> None:
    """Called by the web app at startup: a malformed key stops startup
    instead of the first Schwab call, and production without one is logged."""
    if _cipher() is None and os.getenv("FLY_APP_NAME"):
        logger.warning("TOKEN_ENCRYPTION_KEY is not set — Schwab tokens are stored unencrypted.")


def _decrypt(raw: str) -> str:
    cipher = _cipher()
    if cipher is None:
        raise TokenDecryptError("Schwab token file is encrypted but TOKEN_ENCRYPTION_KEY is not set")
    try:
        return cipher.decrypt(raw.strip().encode()).decode()
    except InvalidToken:
        raise TokenDecryptError("Schwab token file can't be decrypted with TOKEN_ENCRYPTION_KEY") from None


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
    # Schwab call doesn't re-read token.json every time — and can't
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
            raw = f.read()
        if not raw.lstrip().startswith("{"):
            try:
                return json.loads(_decrypt(raw))
            except TokenDecryptError as exc:
                logger.error("%s (%s)", exc, self._file_path)
                raise
        data = json.loads(raw)
        # Plain JSON: saved before a key was set, or written by main.py.
        if _cipher() is not None:
            self._write(data)
            logger.info("Encrypted the plaintext token file %s", self._file_path)
        return data

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
        self._write(stamped)
        self._remember(stamped)
        logger.debug("Tokens saved to %s", self._file_path)

    def _write(self, data: dict) -> None:
        # Atomic replace: write a temp file, then swap it in, so a reader in
        # another process (or this one, on a cache miss) only ever sees the
        # old or the new file — never a truncated, half-written one. 0600:
        # the file grants access to the brokerage account.
        cipher = _cipher()
        content = json.dumps(data, indent=4)
        if cipher is not None:
            content = cipher.encrypt(content.encode()).decode()
        tmp_path = f"{self._file_path}.tmp"
        parent = os.path.dirname(os.path.abspath(self._file_path))
        os.makedirs(parent, mode=0o700, exist_ok=True)
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self._file_path)

    def get_app_credentials(self) -> tuple[str, str, str]:
        return self._credentials or get_app_credentials()


# ─── Per-user token selection (multi-user web app) ──────────────────────
# Each app user has their own Schwab login. The web layer (api/auth.py's
# require_auth) records whose request is running via set_token_owner(), and
# create_token_provider() — which every Schwab client calls — picks that
# user's token store. Being a ContextVar, the owner follows the request into
# FastAPI's handler thread, but NOT into threads a service starts itself
# (e.g. a ThreadPoolExecutor): those must run tasks under
# contextvars.copy_context(), as MarketService.screen_options does.
#
# User LEGACY_OWNER_ID (the bootstrap admin) keeps the original token store
# (TOKEN_FILE / token.json), so the
# single-user setup carries over unchanged; everyone else gets their own.
LEGACY_OWNER_ID = 1
_token_owner: ContextVar[Optional[int]] = ContextVar("schwab_token_owner", default=None)
# Set by the web app at startup: a Schwab call with no owner is then a bug
# (it would otherwise silently use the admin's token — another user's
# account), so it fails closed. CLI use (main.py) leaves it off and gets the
# legacy store, as before.
_owner_required = False


def set_token_owner(user_id: Optional[int]) -> Token:
    return _token_owner.set(user_id)



def require_token_owner() -> None:
    global _owner_required
    _owner_required = True


def user_token_path(user_id: int) -> str:
    """token.json path for `user_id`: the legacy TOKEN_FILE for the
    bootstrap admin, else schwab_tokens/user_<id>.json next to it (so on
    Fly every user's token is on the same /data volume)."""
    base = os.getenv("TOKEN_FILE") or FileTokenProvider._DEFAULT_TOKEN_FILE
    if user_id == LEGACY_OWNER_ID:
        return base
    return os.path.join(os.path.dirname(os.path.abspath(base)), "schwab_tokens", f"user_{user_id}.json")


def delete_user_tokens(user_id: int) -> None:
    """Remove a user's stored Schwab token (admin deleting the user)."""
    if user_id == LEGACY_OWNER_ID:
        raise ValueError("Refusing to delete the bootstrap admin's token store")
    create_token_provider(user_id).invalidate_cache()
    try:
        os.remove(user_token_path(user_id))
    except FileNotFoundError:
        pass


def create_token_provider(user_id: Optional[int] = None) -> TokenProvider:
    """
    The Schwab token store for `user_id`, or for the user whose request is
    running (set_token_owner) when not given.
    """
    owner = user_id if user_id is not None else _token_owner.get()
    if owner is None:
        if _owner_required:
            raise RuntimeError(
                "Schwab call with no user context — refusing to fall back to the admin's token. "
                "Run thread-pool work under contextvars.copy_context()."
            )
        owner = LEGACY_OWNER_ID
    provider = FileTokenProvider(user_token_path(owner))
    logger.debug("Token provider: %s (user %s)", type(provider).__name__, owner)
    return provider
