import base64
import threading
import time
import logging
import requests

from broker.exceptions import BrokerAuthError, BrokerAPIError
from broker.auth import TokenProvider, create_token_provider

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

    Raises :class:`~broker.exceptions.BrokerAuthError` when authentication
    cannot be recovered, and :class:`~broker.exceptions.BrokerAPIError` when
    a non-200 response persists after all retries.
    """

    def __init__(self, base_url: str, token_provider: TokenProvider | None = None) -> None:
        self._token_provider: TokenProvider = token_provider or create_token_provider()
        self.base_url = base_url
        self.access_token = self._token_provider.get_access_token()
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _update_access_token(self) -> None:
        """
        Exchange the refresh token for a new access token via Schwab.

        Thread-safe: uses a global lock so that only one thread performs the
        HTTP refresh at a time.  If another thread already refreshed the token
        while this one was waiting, we simply adopt the new token from storage
        without making a redundant (and fatal) second refresh call.
        """
        with _refresh_lock:
            # Another thread may have already refreshed while we waited.
            stored_token = self._token_provider.get_access_token()
            if stored_token != self.access_token:
                logger.info("Token was refreshed by another thread — adopting new token.")
                self.access_token = stored_token
                self.headers["Authorization"] = f"Bearer {self.access_token}"
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

            self._token_provider.save_tokens(response.json())
            self.access_token = self._token_provider.get_access_token()
            self.headers["Authorization"] = f"Bearer {self.access_token}"
            logger.info("Access token refreshed successfully.")

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

        try:
            response = requests.get(url, headers=self.headers, params=params)
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
            return response.json()

        if response.status_code == 401:
            if attempt >= max_retries:
                raise BrokerAuthError(
                    f"Authentication failed after {max_retries} attempts. "
                    "Re-authenticate using broker.auth.authenticate.get_access_token()."
                )
            logger.warning(
                "401 Unauthorized — refreshing token (attempt %d/%d)…", attempt, max_retries
            )
            self._update_access_token()
            time.sleep(2 ** attempt)
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
