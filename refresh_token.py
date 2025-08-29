import json
import os
import base64
import requests
from loguru import logger
from dotenv import load_dotenv  # Import dotenv to load environment variables

from read_token import get_response_token
from utils import get_app_credentials

# Load environment variables from .env file
load_dotenv()

def refresh_tokens():
    logger.info("Initializing...")

    # Get app credentials from the utility function
    try:
        app_key, app_secret, app_callback_url = get_app_credentials()
    except ValueError as e:
        logger.error(e)
        return None

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
    with open(file_path, 'w') as json_file:
        logger.debug(refresh_token_dict)
        json.dump(refresh_token_dict, json_file, indent=4)

    logger.info("Token dict refreshed.")

    return "Done!"

if __name__ == "__main__":
    refresh_tokens()