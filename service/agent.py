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
    """Get the current price for a given ticker symbol."""
    market_service = MarketService()
    price = market_service.get_ticker_price(symbol)
    return f"The current price of {symbol} is ${price:.2f}" if price else f"Price for {symbol} could not be retrieved."


@function_tool
def get_balances() -> str:
    """Fetch and return the account balances."""
    position_service = PositionService()
    balances = position_service.get_balances()
    return json.dumps(balances) if balances else "Could not retrieve account balances."


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
            instructions="You are a helpful financial assistant. Use tools to fetch real-time data as needed.",
            model=self.model,
            tools=[get_ticker_price, get_balances, get_all_expiration_dates],
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
