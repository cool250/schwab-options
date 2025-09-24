import os
from typing import Any
from dotenv import load_dotenv
from agents import Agent, Runner, RunResult, SQLiteSession, trace
from customagents.research_agents import (
    initialize_report_writer,
    initialize_research_evaluator_agent,
    initialize_financial_analyst,
    initialize_research_analyst,
)
from tools.google_search_tool import google_search
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

        report_writer = initialize_report_writer(self.model)
        research_evaluator = initialize_research_evaluator_agent(self.model)
        financial_analyst = initialize_financial_analyst(self.model)
        research_analyst = initialize_research_analyst(self.model)

        today = date.today().isoformat()
        root_agent = Agent(
            name="Root Financial Agent",
            instructions=(
                """
                1. Use the research_analyst to gather data on a stock.

                 Ask for:
                    - Current stock price and recent movement
                    - Latest quarterly earnings results and performance vs expectations
                    - Recent news and developments
                
                2. Use the financial_analyst to analyze this research data and identify key insights.
                
                3. Use the report_writer to create a comprehensive stock report 
                """
        
            ),
            model=self.model,
            handoffs=[report_writer, financial_analyst, research_analyst],
            tools=[google_search],
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
