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
    Fetch options chain data for a given option symbol within a specified date range.

    """
    logger.info(
        f"Fetching options chain data for {symbol} at {strike}, from {start_date} to {end_date}, contract={contract_type}"
    )
    market_service = MarketService()
    expiration_dates = market_service.get_all_expiration_dates(
        symbol, strike, start_date, end_date, contract_type
    )
    return expiration_dates if expiration_dates else [{"error": "No options chain found."}]


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
