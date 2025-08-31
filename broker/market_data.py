import requests
import requests
from utils import get_access_token
from loguru import logger

class MarketData:
    def __init__(self):
        self.access_token = get_access_token()
        self.base_url = 'https://api.schwabapi.com/marketdata/v1/quotes'
        self.headers = {"Authorization": f"Bearer {self.access_token}",
                        'Accept': 'application/json'}

    def get_stock_quote(self, symbol):

        params = {
            'symbols': symbol,
            'fields': 'quote,fundamental'
        }
    
        try:
            response = requests.get(self.base_url, headers=self.headers, params=params)
            if response.status_code == 200:
                logger.debug(f"Successfully fetched market data for {symbol}: {response.json()}")
                return response.json()
            else:
                logger.error(f"Error: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return None

    def get_price_history(self, symbol, period_type='day', period=2, frequency_type='daily'):
        params = {
            'symbol': symbol,
            'periodType': period_type,
            'period': period
            # 'frequencyType': frequency_type,
            # 'frequency': 1
        }
        
        try:
            response = requests.get(self.base_url, headers=self.headers, params=params)
            logger.debug(f"Request made to {response.url} with headers {self.headers} and params {params}")
            if response.status_code == 200:
                logger.debug(f"Successfully fetched market data for {symbol}: {response.json()}")
                return response.json()
            else:
                logger.error(f"Error : {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return None

