from broker.accounts import AccountsTrading
from broker.authenticate import get_access_token
from broker.refresh_token import refresh_tokens
import requests


if __name__ == "__main__":
    # get_access_token()
    # refresh_tokens()

    acct = AccountsTrading()
    # # acct.fetch_transactions("2025-08-26", "2025-08-28", transaction_type="TRADE")
    securities_account = acct.get_positions()
    if securities_account is not None:
        option_positions_details = acct.get_puts(securities_account)
    else:
        option_positions_details = None
