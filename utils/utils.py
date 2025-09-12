from datetime import datetime
import os

from dotenv import load_dotenv
from loguru import logger


# Load environment variables from .env file
load_dotenv()
TOKEN_FILE_PATH = "token.json"

def get_app_credentials():
    """
    Retrieve app credentials from environment variables.
    Returns:
        tuple: A tuple containing app_key, app_secret, and app_callback_url.
    """
    app_key = os.getenv("APP_KEY")
    app_secret = os.getenv("APP_SECRET")
    app_callback_url = os.getenv("APP_CALLBACK_URL")

    if not app_key or not app_secret or not app_callback_url:
        logger.error("Missing environment variables. Check your .env file.")
        raise ValueError("Environment variables APP_KEY, APP_SECRET, or APP_CALLBACK_URL are missing.")

    return app_key, app_secret, app_callback_url

def convert_to_iso8601(date_string: str) -> str:
        """
        Convert a date string in 'YYYY-MM-DD' format to ISO 8601 format with milliseconds and UTC timezone.
        """
        dt = datetime.strptime(date_string, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%dT00:00:00.000Z")

def get_date_string(datetime_str: str) -> str:
    """
    Convert a datetime string in ISO 8601 format to 'YYYY-MM-DD' format.
    Example: '2023-10-01T00:00:00-04:00' -> '2023-10-01'
    """
    try:
        # Parse the string into a datetime object
        dt = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%S%z")

        # Format the datetime object to only include the date
        date_str = dt.strftime("%Y-%m-%d")
        return date_str
    except ValueError as e:
        logger.error(f"Invalid datetime string: {datetime_str}. Error: {e}")
        return ""