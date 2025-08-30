from broker.accounts import AccountsTrading
from broker.authenticate import get_access_token
from broker.refresh_token import refresh_tokens
import requests


def call_get_exposure():
    """
    Call the FastAPI endpoint to get total exposure for short PUT options.
    """
    url = "http://127.0.0.1:8000/exposure"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            print(f"Total Exposure: {data['total_exposure']}")
        else:
            print(f"Failed to fetch exposure. Status code: {response.status_code}, Detail: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while calling the API: {e}")


if __name__ == "__main__":
    # get_access_token()
    # refresh_tokens()

    # acct = AccountsTrading()
    # # acct.fetch_transactions("2025-08-26", "2025-08-28", transaction_type="TRADE")
    # acct.get_positions()
    call_get_exposure()
