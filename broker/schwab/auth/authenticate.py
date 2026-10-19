import base64
import requests
import webbrowser
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

from broker.schwab.auth.token_provider import get_app_credentials


def construct_init_auth_url() -> tuple[str, str, str, str]:
    # Get app credentials from the utility function
    try:
        app_key, app_secret, app_callback_url = get_app_credentials()
    except ValueError as e:
        logger.error(e)
        raise

    auth_url = f"https://api.schwabapi.com/v1/oauth/authorize?response_type=code&client_id={app_key}&redirect_uri={app_callback_url}"

    logger.info("Click to authenticate:")
    logger.info(auth_url)

    return app_key, app_secret, app_callback_url, auth_url


def construct_headers_and_payload(
    returned_url: str, app_key: str, app_secret: str, app_callback_url: str
) -> tuple[dict[str, str], dict[str, str]]:
    response_code = (
        f"{returned_url[returned_url.index('code=') + 5: returned_url.index('%40')]}@"
    )

    credentials = f"{app_key}:{app_secret}"
    base64_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

    headers: dict[str, str] = {
        "Authorization": f"Basic {base64_credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    payload: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": response_code,
        "redirect_uri": app_callback_url,
    }

    return headers, payload


def build_authorize_url(state: str) -> str:
    """Schwab's login/consent URL for the in-app reconnect flow
    (api/auth.py), carrying `state` so the callback can prove the request
    started from a logged-in session. Same URL shape as
    construct_init_auth_url(), which main.py's CLI flow uses."""
    app_key, _, app_callback_url = get_app_credentials()
    return (
        f"https://api.schwabapi.com/v1/oauth/authorize?response_type=code&client_id={app_key}"
        f"&redirect_uri={app_callback_url}&state={quote(state, safe='')}"
    )


def exchange_authorization_code(code: str) -> dict:
    """Trade the `code` from Schwab's redirect for an access/refresh token
    pair. `code` is the already-URL-decoded value (it ends in "@"), as a web
    framework hands over the query param — main.py's CLI flow instead slices
    it out of the raw pasted URL in construct_headers_and_payload().

    Raises RuntimeError if Schwab doesn't return tokens."""
    app_key, app_secret, app_callback_url = get_app_credentials()
    credentials = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    tokens = retrieve_tokens(
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"},
        payload={"grant_type": "authorization_code", "code": code, "redirect_uri": app_callback_url},
    )
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        logger.error("Schwab code exchange returned no tokens: %s", tokens)
        raise RuntimeError(tokens.get("error_description") or tokens.get("error") or "Schwab returned no tokens")
    return tokens


def retrieve_tokens(headers: dict[str, str], payload: dict[str, str]) -> dict[str, str]:
    init_token_response = requests.post(
        url="https://api.schwabapi.com/v1/oauth/token",
        headers=headers,
        data=payload,
    )

    init_tokens_dict: dict[str, str] = init_token_response.json()

    return init_tokens_dict


def get_access_token() -> str:
    app_key: str
    app_secret: str
    app_callback_url: str
    cs_auth_url: str

    app_key, app_secret, app_callback_url, cs_auth_url = construct_init_auth_url()
    webbrowser.open(cs_auth_url)

    logger.info("Paste Returned URL:")
    returned_url: str = input()

    init_token_headers: dict[str, str]
    init_token_payload: dict[str, str]

    init_token_headers, init_token_payload = construct_headers_and_payload(
        returned_url, app_key, app_secret, app_callback_url
    )

    init_tokens_dict: dict[str, str] = retrieve_tokens(
        headers=init_token_headers, payload=init_token_payload
    )

    # Never log the token response itself: it holds the access and refresh tokens.
    logger.debug("Received Schwab tokens (fields: %s)", ", ".join(sorted(init_tokens_dict)))

    from broker.schwab.auth.token_provider import FileTokenProvider
    FileTokenProvider().save_tokens(init_tokens_dict)

    logger.info("Token dict refreshed.")

    return "Done!"
