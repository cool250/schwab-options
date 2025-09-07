import os
import json
from dotenv import load_dotenv
from loguru import logger
from agents import Agent, Runner, function_tool

from service.market import MarketService
from service.position import PositionService


# -----------------------------
# Define tools
# -----------------------------

@function_tool
def get_ticker_price(symbol: str) -> str:
    """Get the current price for a given ticker symbol."""
    market_service = MarketService()
    price = market_service.get_ticker_price(symbol)
    if price is not None:
        return f"The current price of {symbol} is ${price:.2f}"
    return f"Price for {symbol} could not be retrieved."


@function_tool
def get_balances() -> str:
    """Fetch and return the account balances."""
    position_service = PositionService()
    balances = position_service.get_balances()
    if balances is not None:
        return json.dumps(balances)
    return "Could not retrieve account balances."


@function_tool
def get_all_expiration_dates(symbol: str, strike: float, from_date: str, to_date: str, contract_type: str = "PUT") -> str:
    """
    Fetch the option chain and return all valid expiration dates for a given symbol.

    Rules:
    - 'symbol' is required.
    - 'contract_type' is PUT if not specified.
    - 'from_date' must not be in the past: if a past date is provided, replace it with today's date.
    - 'to_date' must be later than 'from_date'.
    - If 'from_date' equals today, set 'to_date' to 7–10 days after today.
    """
    logger.info(f"Fetching expiration dates for {symbol} at {strike}, from {from_date} to {to_date}, contract={contract_type}")
    market_service = MarketService()
    expiration_dates = market_service.get_all_expiration_dates(symbol, strike, from_date, to_date, contract_type)
    if expiration_dates:
        return json.dumps(expiration_dates)
    return "No expiration dates found."


# -----------------------------
# LLM Service
# -----------------------------

class LLMService:
    def __init__(self):
        self.api_key = self.load_environment()
        self.model = "gpt-4o-mini"

        # Define the agent once
        self.agent = Agent(
            name="Financial Assistant",
            instructions="You are a helpful financial assistant. Use tools to fetch real-time data as needed.",
            model=self.model,
            tools=[get_ticker_price, get_balances, get_all_expiration_dates],
        )

    @staticmethod
    def load_environment():
        """Load environment variables and return the OpenAI API key."""
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in the environment.")
        return api_key

    def invoke_llm(self, query: str) -> str:
        """
        Run a query against the financial agent.
        Uses Runner.run_sync for simplicity.
        """
        result = Runner.run_sync(self.agent, query)
        return result.final_output
