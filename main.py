from service.transactions import TransactionService
from broker.schwab.auth.authenticate import get_access_token
from service.position import PositionService


def authenticate():
    # Implement authentication logic here
    get_access_token()


def position():
    service = PositionService()
    positions = service.get_positions()


def transaction():
    service = TransactionService()
    # transactions = service.get_transaction_history("2025-03-01", "2025-03-30")

    option_transactions = service.get_option_transactions("SPY", "2025-03-01", "2025-03-30")
    print("Option Transactions:", option_transactions)


if __name__ == "__main__":
    authenticate()
    # transaction()
    # position()
