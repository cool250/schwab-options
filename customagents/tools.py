import json
from agents import function_tool
from loguru import logger

from service.market import MarketService
from service.position import PositionService
from service.transactions import TransactionService


@function_tool
def get_ticker_price(symbol: str) -> dict:
    """
    Get the current price for a given ticker symbol.

    Args:
        symbol (str): The ticker symbol of the stock or asset.

    Returns:
        dict: A dictionary containing the ticker symbol and its price, or an error message.
            Example:
            - {"symbol": "AAPL", "price": 150.25}
            - {"error": "Price for AAPL could not be retrieved."}
    """
    market_service = MarketService()
    price = market_service.get_ticker_price(symbol)
    if price:
        return {"symbol": symbol, "price": round(price, 2)}
    return {"error": f"Price for {symbol} could not be retrieved."}


@function_tool
def get_balances() -> dict:
    """
    Fetch and return the account balances.

    Usage examples:
    - "Get current balance" → get_balances()
    - "Fetch account balances" → get_balances()

    This function interacts with the PositionService to retrieve account balances.

    Returns:
        dict: A dictionary containing account balances if available, or an error message.
            Example:
            - {'margin': 734369.11, 'mutualFundValue': 328491.12, 'account': 1353144.52}
            - {"error": "Could not retrieve account balances."}
    """
    position_service = PositionService()
    balances = position_service.get_balances()
    return balances if balances else {"error": "Could not retrieve account balances."}


@function_tool
def get_options_chain(
    symbol: str,
    strike: float,
    start_date: str,
    end_date: str,
    contract_type: str = "ALL",
) -> list[dict]:
    """
    Fetch all valid expiration dates for a given option symbol within a specified date range.

    Args:
        symbol (str): The ticker symbol of the option (e.g., "AAPL").
        strike (float): The strike price of the option.
        start_date (str): The start date of the range (format: "YYYY-MM-DD").
        end_date (str): The end date of the range (format: "YYYY-MM-DD").
        contract_type (str, optional): The type of option contract. Defaults to "ALL".

    Returns:
        list[dict]: A list of dictionaries containing expiration dates if found, or an error message.
            Example:
            - [{"expiration_date": "2025-10-01"}, {"expiration_date": "2025-10-15"}]
            - [{"error": "No expiration dates found."}]
    """
    logger.info(
        f"Fetching expiration dates for {symbol} at {strike}, from {start_date} to {end_date}, contract={contract_type}"
    )
    market_service = MarketService()
    expiration_dates = market_service.get_all_expiration_dates(
        symbol, strike, start_date, end_date, contract_type
    )
    return expiration_dates if expiration_dates else [{"error": "No expiration dates found."}]


@function_tool
def get_option_transactions(
    start_date: str,
    end_date: str,
    stock_ticker: str,
    contract_type: str = "ALL",
    realized_gains_only: bool = True,
) -> list[dict]:
    """
    Fetch option transactions based on user-defined criteria.

    Args:
        start_date (str): The start date for the transaction query in the format 'YYYY-MM-DD'.
        end_date (str): The end date for the transaction query in the format 'YYYY-MM-DD'.
        stock_ticker (str): The stock ticker symbol to filter transactions (e.g., 'AAPL').
        contract_type (str, optional): The type of option contract to filter by. Defaults to "ALL".
        realized_gains_only (bool, optional): Whether to include only transactions with realized gains. Defaults to True.

    Returns:
        list[dict]: A list of dictionaries representing the filtered transactions, or an error message.
            Example:
            - [{"date": "2025-09-01", "symbol": "AAPL", "type": "CALL", "price": 150.0}]
            - [{"error": "No transactions found."}]
    """
    transaction_service = TransactionService()
    transactions = transaction_service.get_option_transactions(
        start_date=start_date,
        end_date=end_date,
        stock_ticker=stock_ticker,
        contract_type=contract_type,
        realized_gains_only=realized_gains_only,
    )
    return transactions if transactions else [{"error": "No transactions found."}]
