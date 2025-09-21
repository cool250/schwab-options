import os
from typing import Any
from dotenv import load_dotenv
from agents import Agent, Runner, RunResult, SQLiteSession, trace
from customagents.brokerage_agents import (
    initialize_options_chain_agent,
    initialize_balances_agent,
    initialize_transactions_agent,
)
import asyncio
import json

from typing import Any
from datetime import date

from loguru import logger


class AgentService:
    def __init__(self):
        self.api_key = self._load_environment()
        self.model = "gpt-4o-mini"
        self.runner = Runner()

        self.root_agent = self._initialize_agent()
        self.session = SQLiteSession("conversation_123") # Use a unique session name

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
        input = f'{{"role": "user", "content": "{query}"}}'

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        with trace(workflow_name="Conversation with Financial Agent"):
            # Pass `input` to `run_sync`
            result: RunResult = self.runner.run_sync(self.root_agent, input=input, session=self.session)
            logger.debug(f"RunResult dir: {dir(result)}")
            assistant_reply = str(result.final_output)
        
        return assistant_reply
