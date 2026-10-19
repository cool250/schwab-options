import base64
import threading
import time
import logging
import requests

from broker.schwab.exceptions import BrokerAuthError, BrokerAPIError
from broker.schwab.auth import TokenProvider, create_token_provider

logger = logging.getLogger(__name__)

_SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"

# Global lock: only one thread may refresh tokens at a time.
# Schwab rotates refresh tokens on every use, so concurrent refreshes
# cause the second attempt to fail with 400.
_refresh_lock = threading.Lock()


class BaseClient:
    """
    Base HTTP client for Schwab API sub-clients.

    Handles Bearer-token auth, automatic token refresh on 401, and
    exponential-backoff retries.

    Raises :class:`~broker.schwab.exceptions.BrokerAuthError` when authentication
    cannot be recovered, and :class:`~broker.schwab.exceptions.BrokerAPIError` when
    a non-200 response persists after all retries.
    """

    def __init__(self, base_url: str, token_provider: TokenProvider | None = None) -> None:
        self._token_provider: TokenProvider = token_provider or create_token_provider()
        self.base_url = base_url

    def _current_access_token(self) -> str:
        """The access token to send — refreshed first if it's about to
        expire, rather than waiting for Schwab to 401 the request.

        Raises BrokerAuthError when no token is stored at all (e.g. a fresh
        deploy before Settings → Connect Schwab): a missing/unreadable
        token.json or an empty Redis key is an auth problem, not a server
        error, so it surfaces as app.py's 503 "reconnect" path instead of a
        bare 500."""
        if self._token_provider.access_token_expires_soon():
            self._refresh_access_token(failed_token=None)
        try:
            token = self._token_provider.get_access_token()
        except (OSError, ValueError) as exc:  # FileNotFoundError, JSONDecodeError, Redis "not found"
            raise BrokerAuthError("No Schwab token found — connect Schwab in Settings.") from exc
        if not token:
            raise BrokerAuthError("No Schwab token found — connect Schwab in Settings.")
        return token

    def _auth_headers(self, token: str | None = None) -> dict:
        return {
            "Authorization": f"Bearer {token or self._current_access_token()}",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _refresh_access_token(self, failed_token: str | None) -> None:
        """
        Exchange the refresh token for a new access token via Schwab.

        `failed_token` is the access token a request just got a 401 with, or
        None for a proactive refresh (token about to expire).

        Thread-safe: uses a global lock so that only one thread performs the
        HTTP refresh at a time, and re-checks after acquiring it — a thread
        that waited while another refreshed finds a newer token (or one no
        longer near expiry) and skips its own, now-redundant refresh.
        """
        with _refresh_lock:
            if failed_token is None:
                if not self._token_provider.access_token_expires_soon():
                    return
            elif self._token_provider.get_access_token() != failed_token:
                return

            app_key, app_secret, _ = self._token_provider.get_app_credentials()
            refresh_token = self._token_provider.get_refresh_token()

            response = requests.post(
                _SCHWAB_TOKEN_URL,
                headers={
                    "Authorization": (
                        f"Basic {base64.b64encode(f'{app_key}:{app_secret}'.encode()).decode()}"
                    ),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            )

            if response.status_code != 200:
                raise BrokerAuthError(
                    f"Token refresh failed ({response.status_code}): {response.text}"
                )

            token_data = response.json()
            # Whether Schwab rotates the refresh token on every refresh
            # decides how often it must be persisted and whether Settings'
            # 7-day expiry (refresh_token_issued_at) is right — logged on
            # every refresh until that's confirmed.
            new_refresh = token_data.get("refresh_token")
            if new_refresh and new_refresh != refresh_token:
                logger.warning("Access token refreshed — Schwab issued a NEW refresh token (rotated).")
            else:
                logger.info("Access token refreshed — refresh token unchanged.")
            self._token_provider.save_tokens(token_data)

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def _fetch_data(
        self,
        url: str | None = None,
        params: dict | None = None,
        attempt: int = 1,
        max_retries: int = 3,
    ) -> dict:
        """
        Perform a GET request with automatic retry and token refresh.

        Parameters
        ----------
        url:
            Full URL to request; defaults to ``self.base_url``.
        params:
            Query-string parameters.
        attempt:
            Current attempt number (internal, used for recursion).
        max_retries:
            Maximum number of attempts before raising.

        Returns
        -------
        dict
            Parsed JSON response body.

        Raises
        ------
        BrokerAuthError
            When a 401 response persists after a token refresh retry.
        BrokerAPIError
            When a non-200 response persists after *max_retries* attempts.
        """
        if url is None:
            url = self.base_url

        token = self._current_access_token()
        try:
            response = requests.get(url, headers=self._auth_headers(token), params=params)
        except requests.RequestException as exc:
            if attempt < max_retries:
                logger.warning("Request error (attempt %d/%d): %s", attempt, max_retries, exc)
                time.sleep(2 ** attempt)
                return self._fetch_data(url, params, attempt + 1, max_retries)
            raise BrokerAPIError(
                f"Request failed after {max_retries} attempts: {exc}"
            ) from exc

        logger.debug("status=%s  url=%s", response.status_code, response.url)

        if response.status_code == 200:
            data = response.json()
            # Size only: bodies are account data (positions, balances,
            # transactions), which shouldn't end up in logs or `fly logs`.
            logger.debug("response: %d bytes, %s", len(response.content), type(data).__name__)
            return data

        if response.status_code == 401:
            if attempt >= max_retries:
                raise BrokerAuthError(
                    f"Authentication failed after {max_retries} attempts. "
                    "Re-authenticate using broker.schwab.auth.authenticate.get_access_token()."
                )
            logger.warning(
                "401 Unauthorized — refreshing token (attempt %d/%d)…", attempt, max_retries
            )
            # Reload from the store first, in case the token was replaced
            # outside this process (e.g. Redis written by another instance).
            self._token_provider.invalidate_cache()
            self._refresh_access_token(failed_token=token)
            # No backoff sleep here: a fresh token needs no wait, unlike the
            # transient-error retries below.
            return self._fetch_data(url, params, attempt + 1, max_retries)

        if attempt < max_retries:
            logger.warning(
                "HTTP %s — retrying (attempt %d/%d)…",
                response.status_code, attempt, max_retries,
            )
            time.sleep(2 ** attempt)
            return self._fetch_data(url, params, attempt + 1, max_retries)

        raise BrokerAPIError(
            f"API error after {max_retries} attempts: "
            f"{response.status_code} {response.text}",
            status_code=response.status_code,
        )
