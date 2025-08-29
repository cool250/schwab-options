import json
import os
from flask import Request
import base64
import requests
from loguru import logger

from read_token import get_response_token


def refresh_tokens():
    logger.info("Initializing...")

    app_key = "Li6cHgVMldtne0pGZezXOYJDgZADm0fG"
    app_secret = "AcYsWMPemzwIbTnD"
    app_callback_url = "https://127.0.0.1"

    # Read the refresh token value from the token.json file
    file_path = "token.json"
    refresh_token_value = get_response_token()

    if refresh_token_value == "Token not found":
        logger.error("Refresh token not found in the file.")
        return None

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_value,
    }
    headers = {
        "Authorization": f'Basic {base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()}',
        "Content-Type": "application/x-www-form-urlencoded",
    }

    refresh_token_response = requests.post(
        url="https://api.schwabapi.com/v1/oauth/token",
        headers=headers,
        data=payload,
    )
    if refresh_token_response.status_code == 200:
        logger.info("Retrieved new tokens successfully using refresh token.")
    else:
        logger.error(
            f"Error refreshing access token: {refresh_token_response.text}"
        )
        return None

    refresh_token_dict = refresh_token_response.json()

    logger.debug(refresh_token_dict)

    # Convert and save as JSON
    file_path = "token.json"
    with open(file_path, 'w') as json_file:
        logger.debug(refresh_token_dict)
        json.dump(refresh_token_dict, json_file, indent=4)

    logger.info("Token dict refreshed.")

    return "Done!"

if __name__ == "__main__":
  refresh_tokens()