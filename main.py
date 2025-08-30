from broker.accounts import AccountsTrading
from broker.authenticate import get_access_token
from broker.refresh_token import refresh_tokens


if __name__ == "__main__":
    # get_access_token()
    # refresh_tokens()

    acct = AccountsTrading()
    # acct.get_transactions("2025-08-26", "2025-08-28", transaction_type="TRADE")
    acct.get_positions()