import os
from dotenv import load_dotenv
from loguru import logger
from openai import OpenAI
import json

from service.market import MarketService
from service.position import PositionService

class LLMService:
    def __init__(self):
        self.api_key = self.load_environment()
        self.model="gpt-4o-mini"
        self.client = self.initialize_client(self.api_key)

    @staticmethod
    def load_environment():
        """Load environment variables and return the OpenAI API key."""
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in the environment.")
        return api_key

    def initialize_client(self, api_key):
        """Initialize and return the OpenAI client."""
        return OpenAI(api_key=api_key)

    @staticmethod
    def define_tools():
        """Define and return the list of tools for the model."""
        return [
            {
            "type": "function",
            "name": "get_ticker_price",
            "description": "Get the current price for a given ticker symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                "symbol": {
                    "type": "string",
                    "description": "The ticker symbol for the asset, e.g., AAPL, TSLA.",
                },
                },
                "required": ["symbol"],
            },
            },
            {
            "type": "function",
            "name": "get_balances",
            "description": "Fetch and return the account balances.",
            "parameters": {
                "type": "object",
                "properties": {}
            },
            },
            {
            "type": "function",
            "name": "get_all_expiration_dates",
            "description": (
                    "Fetch the option chain and return all valid expiration dates for a given symbol. "
                    "Rules: "
                    "- 'symbol' is required. "
                    "- 'contract_type' is PUT if not specified. "
                    "- 'from_date' must not be in the past: if a past date is provided, replace it with today's date. "
                    "- 'to_date' must be later than 'from_date'. "
                    "- If 'from_date' equals today, set 'to_date' to 7–10 days after today."
                ),
            "parameters": {
                "type": "object",
                "properties": {
                "symbol": {
                    "type": "string",
                    "description": "The ticker symbol for the asset, e.g., AAPL, TSLA.",
                },
                "strike": {
                    "type": "number",
                    "description": "The strike price to filter options.",
                },
                "from_date": {
                    "type": "string",
                    "description": "The start date for option chain data (format: 'YYYY-MM-DD'). .",
                },
                "to_date": {
                    "type": "string",
                    "description": "The end date for option chain data (format: 'YYYY-MM-DD').",
                },
                "contract_type": {
                    "type": "string",
                    "description": "The type of contract, e.g., PUT or CALL.",
                    "default": "PUT",
                },
                },
                "required": ["symbol", "strike", "from_date", "to_date"],
            },
            },
        ]

    @staticmethod
    def get_ticker_price(symbol):
        """Return the current price for the given ticker symbol."""
        market_service = MarketService()
        price = market_service.get_ticker_price(symbol)
        if price is not None:
            return f"The current price of {symbol} is ${price:.2f}"
        return f"Price for {symbol} could not be retrieved."

    @staticmethod
    def get_balances():
        position_service = PositionService()
        balances = position_service.get_balances()
        if balances is not None:
            return balances
        return "Could not retrieve account balances."

    @staticmethod
    def get_all_expiration_dates(symbol, strike, from_date, to_date, contract_type="PUT"):
        """Fetch all expiration dates for a given strike price."""
        logger.info(f"Fetching expiration dates for {symbol} with strike {strike} from {from_date} to {to_date} as {contract_type}")
        market_service = MarketService()
        expiration_dates = market_service.get_all_expiration_dates(symbol, strike, from_date, to_date, contract_type)
        if expiration_dates:
            return expiration_dates
        return "No expiration dates found."

    def call_function(self, name, args):
        if name == "get_ticker_price":
            return self.get_ticker_price(**args)
        if name == "get_balances":
            return self.get_balances()
        if name == "get_all_expiration_dates":
            return self.get_all_expiration_dates(**args)

    def invoke_llm(self, query: str):
        tools = self.define_tools()

        input_list = [
            {"role": "user", "content": query}
        ]
        last_tool_results = None

        # Loop until we get a final response from the model
        while True:
            # 2. Prompt the model with tools defined
            response = self.client.responses.create(
                instructions="You are a helpful financial assistant. Use the tools to fetch real-time data as needed.",
                model=self.model,
                tools=tools,
                input=input_list,
                tool_choice="auto"
            )

            # If model produced final text, return it
            if response.output_text:
                return response.output_text

            # Extract tool calls
            tool_calls = [o for o in response.output if o.type == "function_call"]

            if not tool_calls:
                return last_tool_results or "No response generated."

            for tool_call in tool_calls:
                name = tool_call.name
                args = json.loads(tool_call.arguments)

                result = self.call_function(name, args)
                last_tool_results = str(result)

                # Append the assistant’s tool call
                input_list.append(tool_call.dict())
                
                input_list.append({
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": last_tool_results
                })