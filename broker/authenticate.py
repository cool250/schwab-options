import json
import base64
import requests
import webbrowser
import logging

logger = logging.getLogger(__name__)

from utils import get_app_credentials, TOKEN_FILE_PATH


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

    logger.debug(init_tokens_dict)

    # Convert and save as JSON
    with open(TOKEN_FILE_PATH, "w") as json_file:
        logger.debug(init_tokens_dict)
        json.dump(init_tokens_dict, json_file, indent=4)

    logger.info("Token dict refreshed.")

    return "Done!"
