from loguru import logger
import requests
from broker.refresh_token import refresh_tokens
from utils.read_token import get_access_token


class APIClient:
    """
    Parent class for common API client functionality.
    """
    def __init__(self, base_url):
        self.access_token = get_access_token()
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json"
        }

    def _update_access_token(self):
        """Refresh and update the access token."""
        refresh_tokens()
        self.access_token = get_access_token()
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json"
        }

    def _fetch_data(self, url=None, params=None, attempt=1, max_retries=3):
        """Helper method to fetch data from the API."""
        try:
            if url is None:
                url = self.base_url
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                logger.warning("Token expired. Refreshing token and retrying...")
                self._update_access_token()
                return self._fetch_data(url, params)
            elif attempt < max_retries:
                logger.warning(f"Retrying... (Attempt {attempt + 1}/{max_retries})")
                return self._fetch_data(url, params, attempt + 1)
            else:
                logger.error(f"Error fetching data: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return None
