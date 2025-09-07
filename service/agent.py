import os
import json
from dotenv import load_dotenv
from loguru import logger
from agents import Agent, Runner, function_tool
from service.market import MarketService
from service.position import PositionService
import asyncio


# -----------------------------
# Define tools
# -----------------------------

@function_tool
def get_ticker_price(symbol: str) -> str:
    """
    Get the current price for a given ticker symbol.

    Args:
        symbol (str): The ticker symbol of the stock or asset.

    Returns:
        str: A formatted string containing the current price of the ticker symbol 
             or an error message if the price could not be retrieved.
    """
    market_service = MarketService()
    price = market_service.get_ticker_price(symbol)
    return f"The current price of {symbol} is ${price:.2f}" if price else f"Price for {symbol} could not be retrieved."


@function_tool
def get_balances() -> str:
    """
    Fetch and return the account balances.

    Usage examples:
    - "Get current balance" → get_balances()
    - "Fetch account balances" → get_balances()

    This function interacts with the PositionService to retrieve account balances.
    If balances are successfully retrieved, they are returned as a JSON-formatted string.
    If no balances are available, an error message is returned.

    Returns:
        str: A JSON-formatted string of account balances if available, 
             otherwise an error message indicating the failure to retrieve balances.
    """
    position_service = PositionService()
    balances = position_service.get_balances()
    return json.dumps(balances) if balances else "Could not retrieve account balances."


@function_tool
def get_options_chain(symbol: str, strike: float, start_date: str, end_date: str, contract_type: str = "ALL") -> str:
    """
    Fetch all valid expiration dates for a given option symbol within a specified date range.
    Always pass start_date more than today's date.

    Usage examples:
    - "Get Options Chain for AAPL around strike 150" → start_date=today, end_date=+30 days
    - "Show Put Chain for TSLA for from 2025-10-01 to 2025-10-21 around strike 700" → get_options_chain("TSLA", strike=700, start_date="2025-10-01", end_date="2025-10-21", contract_type="PUT")

    Args:
        symbol (str): The ticker symbol of the option (e.g., "AAPL").
        strike (float): The strike price of the option.
        start_date (str): 
            The start date of the range (format: "YYYY-MM-DD"). 
            Must be **today or a future date**. If the user does not specify, default to today's date.
        end_date (str): 
            The end date of the range (format: "YYYY-MM-DD"). 
            Must also be today or later. If the user does not specify, default to one month from today.
        contract_type (str, optional): The type of option contract. Defaults to "ALL". Use "PUT" for put options or "CALL" for call options.

    Returns:
        str: A JSON string containing the expiration dates if found, or a message indicating no expiration dates were found.

    Raises:
        ValueError: If 'to_date' is earlier than 'from_date'.
        TypeError: If any of the arguments are of an incorrect type.

    Notes:
        - The function logs the operation details for debugging purposes.
        - The 'from_date' and 'to_date' are adjusted to ensure they conform to the rules specified.
    """
    logger.info(f"Fetching expiration dates for {symbol} at {strike}, from {start_date} to {end_date}, contract={contract_type}")
    market_service = MarketService()
    expiration_dates = market_service.get_all_expiration_dates(symbol, strike, start_date, end_date, contract_type)
    return json.dumps(expiration_dates) if expiration_dates else "No expiration dates found."


# -----------------------------
# Agent Service
# -----------------------------

class AgentService:
    def __init__(self):
        self.api_key = self._load_environment()
        self.model = "gpt-4o-mini"
        self.runner = Runner()
        self.agent = self._initialize_agent()

    @staticmethod
    def _load_environment() -> str:
        """Load environment variables and return the OpenAI API key."""
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in the environment.")
        return api_key

    def _initialize_agent(self) -> Agent:
        """Initialize and return the agent."""
        return Agent(
            name="Financial Assistant",
            instructions=(
                "You are a helpful financial assistant. Use tools to fetch real-time data as needed. "
                "If the user does not provide a strike price for the 'get_all_expiration_dates' tool, "
                "fetch the current price using the 'get_ticker_price' tool and use it as the strike." \
                "When displaying an option chain, always separate Calls and Puts into two clear tables. "
                "Ensure the tables include expiration date, strike, price, and annualized return if available."
            ),
            model=self.model,
            tools=[get_ticker_price, get_balances, get_options_chain],
        )

    def invoke_llm(self, query: str) -> str:
        """Run a query against the financial agent."""
        # Ensure an event loop exists in the current thread
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = self.runner.run_sync(self.agent, query)
        return result.final_output
