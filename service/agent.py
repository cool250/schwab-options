import os
import json
import uuid
import asyncio
from typing import Any, Dict, Union, Optional
from datetime import date, datetime
from dotenv import load_dotenv
from agents import Agent, Runner, RunResult, SQLiteSession, trace
from customagents.brokerage_agents import (
    initialize_options_chain_agent,
    initialize_balances_agent,
    initialize_transactions_agent,
)
import logging

logger = logging.getLogger(__name__)


class AgentService:
    """
    Service class for handling agent-based interactions with financial data.
    
    This class manages the initialization, configuration, and invocation of 
    various specialized agents for financial tasks such as retrieving options chains,
    account balances, and transaction data.
    """
    
    def __init__(self, session_id: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Initialize the AgentService.
        
        Args:
            session_id (str, optional): Unique identifier for the conversation session.
                If None, a UUID will be generated.
            model (str, optional): The LLM model to use. Defaults to "gpt-4o-mini".
        """
        self.api_key = self._load_environment()
        self.model = model
        self.runner = Runner()
        
        # Create a unique session ID if not provided
        if not session_id:
            session_id = f"conversation_{uuid.uuid4().hex[:8]}"
            
        self.session = SQLiteSession(session_id)
        self.root_agent = self._initialize_agent()
        logger.info(f"AgentService initialized with session ID: {session_id}")

    @staticmethod
    def _load_environment() -> str:
        """
        Load environment variables and return the OpenAI API key.
        
        Returns:
            str: The OpenAI API key.
            
        Raises:
            ValueError: If OPENAI_API_KEY is not set in the environment.
        """
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY is not set in the environment.")
            raise ValueError("OPENAI_API_KEY is not set in the environment.")
        return api_key

    def _initialize_agent(self) -> Agent:
        """
        Initialize and return the root agent with handoffs to specialized sub-agents.
        
        Returns:
            Agent: The initialized root agent with configured sub-agents.
        """
        # Initialize specialized agents
        options_chain_agent = initialize_options_chain_agent(self.model)
        balances_agent = initialize_balances_agent(self.model)
        transactions_agent = initialize_transactions_agent(self.model)

        # Get current date for context
        today = date.today().isoformat()
        
        # Create the root agent with proper instructions
        root_agent = Agent(
            name="Root Financial Agent",
            instructions=(
                "You are the root financial agent responsible for routing queries to specialized sub-agents.\n\n"
                f"Today's date is {today}.\n\n"
                "Guidelines:\n"
                "1. Route queries to the appropriate specialized agent based on intent:\n"
                "   - Options chain requests → Options Chain Agent\n"
                "   - Balance inquiries → Balances Agent\n"
                "   - Transaction history → Transactions Agent\n"
                "2. Never answer financial queries directly without using the appropriate agent.\n"
                "3. Ask clarifying questions only when the user's intent is genuinely unclear.\n"
                "4. Preserve context between interactions for follow-up questions.\n"
                "5. Include error handling for invalid inputs.\n"
                "6. Always provide clear, concise responses.\n"
            ),
            model=self.model,
            handoffs=[options_chain_agent, balances_agent, transactions_agent],
        )
        return root_agent

    def invoke_llm(self, query: str) -> Union[Dict[str, Any], str]:
        """
        Run a query against the financial agent system.
        
        Args:
            query (str): The user query to process.
            
        Returns:
            Union[Dict[str, Any], str]: The agent's response, either as a dictionary or string.
            
        Raises:
            Exception: If there's an error during agent invocation.
        """
        if not query or not query.strip():
            return "Please provide a valid query."
        
        try:
            # Sanitize input to prevent injection
            sanitized_query = json.dumps(query)[1:-1]  # Remove outer quotes from JSON string
            
            # Format input for the agent
            input_data = json.dumps({"role": "user", "content": sanitized_query})
            
            # Ensure we have an active event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            logger.info(f"Processing query: {sanitized_query[:50]}{'...' if len(sanitized_query) > 50 else ''}")
            
            # Trace the agent's execution for monitoring
            with trace(workflow_name="Financial Agent Conversation"):
                # Run the query through the agent system
                start_time = datetime.now()
                result: RunResult = self.runner.run_sync(
                    self.root_agent, 
                    input=input_data, 
                    session=self.session
                )
                execution_time = (datetime.now() - start_time).total_seconds()
                
                # Process the result
                assistant_reply = str(result.final_output)
                logger.info(f"Query processed in {execution_time:.2f} seconds")
                
            return assistant_reply
            
        except Exception as e:
            logger.error(f"Error in invoke_llm: {str(e)}", exc_info=True)
            return f"I encountered an error while processing your request. Please try again or rephrase your query. Error: {str(e)}"
