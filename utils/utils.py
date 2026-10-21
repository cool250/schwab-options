from datetime import datetime

from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)


# Load environment variables from .env file
load_dotenv()
def convert_to_iso8601(date_string: str) -> str:
        """
        Convert a date string in 'YYYY-MM-DD' format to ISO 8601 format with milliseconds and UTC timezone.
        """
        dt = datetime.strptime(date_string, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%dT00:00:00.000Z")

    
def get_date_object(date_string: str) -> datetime:
    """
    Convert a date string in 'YYYY-MM-DD' format to a datetime object.
    """
    try:
        return datetime.strptime(date_string, "%Y-%m-%d")
    except ValueError as e:
        logger.error(f"Invalid date string: {date_string}. Error: {e}")
        return None
    
def get_date_string(date_obj: datetime) -> str:
    """
    Convert a datetime object to a date string in 'YYYY-MM-DD' format.
    """
    if not isinstance(date_obj, datetime):
        logger.error(f"Invalid date object: {date_obj}. Must be a datetime instance.")
        return ""
    return date_obj.strftime("%Y-%m-%d")

