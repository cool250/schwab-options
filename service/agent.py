import os
import json
from typing import Any
from dotenv import load_dotenv
from loguru import logger
from agents import Agent, Runner, function_tool, MessageOutputItem, RunResult
from customagents.brokerage_agents import initialize_options_chain_agent, initialize_balances_agent, initialize_transactions_agent
from service.market import MarketService
from service.position import PositionService
from service.transactions import TransactionService
import asyncio

from typing import Any
import json
from loguru import logger
from datetime import date



class AgentService:
    def __init__(self):
        self.api_key = self._load_environment()
        self.model = "gpt-4o-mini"
        self.runner = Runner()

        self.root_agent = self._initialize_agent()
        
        # History list of turns as dicts: role + content
        self.history: list[dict[str, str]] = []

    @staticmethod
    def _load_environment() -> str:
        """Load environment variables and return the OpenAI API key."""
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in the environment.")
        return api_key

    def _initialize_agent(self) -> Agent:
        """Initialize and return the root agent with handoffs."""

        options_chain_agent = initialize_options_chain_agent(self.model)
        balances_agent = initialize_balances_agent(self.model)
        transactions_agent = initialize_transactions_agent(self.model)

        today = date.today().isoformat()
        root_agent = Agent(
            name="Root Financial Agent",
            instructions=(
                "You are the root agent.\n"
                f"Today's date is {today}.\n"
                "- Route the query to the correct sub-agent.\n"
                "- Never answer financial queries directly.\n"
                "- Ask clarifying questions only if intent is unclear.\n"
            ),
            model=self.model,
            handoffs=[options_chain_agent, balances_agent, transactions_agent],
        )
        return root_agent

    def invoke_llm(self, query: str) -> dict[str, Any] | str:
        """Run a query against the financial agent."""
        
        # Append the user query to history
        self.history.append({"role": "user", "content": query})

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Call the agent, passing the history
        result: RunResult = self.runner.run_sync(
            self.root_agent,
            input=self.history
        )

        # result.final_output is either structured or text
        # Append assistant reply to history
        assistant_reply = str(result.final_output)
        self.history.append({"role": "assistant", "content": assistant_reply})

        # Maintain history length to a maximum of 4 entries
        if len(self.history) > 4:
            self.history = self.history[-4:]

        return assistant_reply
