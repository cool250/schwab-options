import time
from loguru import logger
import requests
from broker.refresh_token import refresh_tokens
from utils.read_token import get_access_token
import json


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
        
            full_url = requests.Request('GET', url, params=params).prepare().url
            logger.debug(f"Full request URL: {full_url}")
            response = requests.get(url, headers=self.headers, params=params)
            logger.info(f"Received response with status code {response.status_code}")
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    logger.debug(f"Response JSON: {json.dumps(response_data) }")
                    return response_data
                except ValueError as e:
                    logger.error(f"Error decoding JSON response: {str(e)}")
                    return None
            elif response.status_code == 401 and attempt < max_retries:
                logger.warning(f"Token expired. Refreshing token and retrying...{attempt + 1}/{max_retries}")
                self._update_access_token()
                time.sleep(2 ** attempt)  # Exponential backoff
                return self._fetch_data(url, params,attempt + 1)
            elif attempt < max_retries:  # Retry for other errors
                logger.warning(f"Retrying... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(2 ** attempt)  # Exponential backoff
                return self._fetch_data(url, params, attempt + 1)
            else:
                logger.error(f"Error fetching data: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return None
