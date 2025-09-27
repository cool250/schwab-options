"""
Research Agent Service

This module provides a service for conducting company research using specialized AI agents.
It coordinates a workflow of data collection, analysis, and report generation.
"""

import os
import re
import json
import asyncio
import uuid
from typing import Any, Dict, Union, Optional
from datetime import date, datetime
from dotenv import load_dotenv
from agents import Agent, Runner, RunResult, SQLiteSession, trace
from customagents.research_agents import (
    initialize_report_writer,
    initialize_research_evaluator_agent,
    initialize_financial_analyst,
    initialize_research_analyst,
)
from tools.google_search_tool import google_search
from loguru import logger


class ResearchAgentService:
    """
    Service for performing comprehensive company research using specialized AI agents.
    
    This service manages a system of specialized agents that work together to:
    1. Collect financial data about a company
    2. Evaluate and analyze the collected data
    3. Generate comprehensive financial reports
    
    The service handles agent coordination, parameter passing, and result processing.
    """

    def __init__(self, company_name: str, session_id: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Initialize the ResearchAgentService.
        
        Args:
            company_name (str): The name of the company to research.
            session_id (str, optional): Unique identifier for the conversation session.
                If None, a UUID will be generated.
            model (str, optional): The LLM model to use. Defaults to "gpt-4o-mini".
        """
        self.api_key = self._load_environment()
        self.model = model
        self.runner = Runner()
        self.company_name = company_name

        # Create a unique session ID if not provided
        if not session_id:
            session_id = f"research_{uuid.uuid4().hex[:8]}"
            
        self.session = SQLiteSession(session_id)
        self.root_agent = self._initialize_agent()
        logger.info(f"ResearchAgentService initialized with session ID: {session_id}")

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
        
    def _extract_company_name(self, query: str) -> str:
        """
        Extract the company name from the query using regex patterns.
        
        Args:
            query (str): The user query.
            
        Returns:
            str: The extracted company name, or an empty string if not found.
        """
        # Try to find company name patterns like "research COMPANY" or "report for COMPANY"
        patterns = [
            r"(?:research|analyze|report for|info on|data about|information on)\s+([A-Z][A-Za-z0-9\s]+)",
            r"([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*)\s+(?:stock|company|corporation|inc|analysis)",
            r"([A-Z]{1,5})\s+(?:stock|company|ticker)",  # For ticker symbols
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                return match.group(1).strip()
                
        # Default fallback - look for capitalized words that might be company names
        words = query.split()
        for i, word in enumerate(words):
            if word[0].isupper() and len(word) > 1:
                # Check if this might be part of a multi-word company name
                if i < len(words) - 1 and words[i+1][0].isupper():
                    return f"{word} {words[i+1]}"
                return word
                
        return ""

    def _initialize_agent(self) -> Agent:
        """
        Initialize and return the root agent with handoffs to specialized sub-agents.
        
        Returns:
            Agent: The initialized root agent with configured sub-agents.
        """
        # Initialize specialized research agents
        report_writer = initialize_report_writer(self.model)
        research_evaluator = initialize_research_evaluator_agent(self.model)
        financial_analyst = initialize_financial_analyst(self.model)
        research_analyst = initialize_research_analyst(self.model, self.company_name)

        today = date.today().isoformat()
        root_agent = Agent(
            name="Root Research Agent",
            instructions=(
                "# Company Research Coordinator\n\n"
                f"Today's date: {today}\n\n"
                "You coordinate a multi-stage research process for analyzing companies. Follow this workflow:\n\n"
                "## Research Workflow\n\n"
                "1. **Data Collection**: Use the research_analyst to gather comprehensive data about the company.\n"
                "   - Replace all instances of 'COMPANY_NAME' with the actual company name when passing to sub-agents\n"
                "   - Collect current stock price and recent movement\n"
                "   - Find latest quarterly earnings results and performance vs expectations\n"
                "   - Gather recent news and developments\n\n"
                "2. **Data Validation**: Have the research_evaluator agent verify the quality and completeness of the data.\n"
                "   - If data quality is rated POOR or FAIR, return to research_analyst for more data\n\n"
                "3. **Analysis**: Use the financial_analyst to analyze the research data and identify key insights.\n"
                "   - Replace all instances of 'COMPANY_NAME' with the actual company name\n"
                "   - Ensure all analysis is based on verified data\n\n"
                "4. **Report Generation**: Use the report_writer to create a comprehensive stock report.\n"
                "   - Replace all instances of 'COMPANY_NAME' with the actual company name\n"
                "   - Ensure the report is properly formatted and complete\n\n"
                "## Parameter Passing Requirements\n\n"
                "- Always include the company_name parameter when calling any sub-agent\n"
                "- Replace all instances of 'COMPANY_NAME' in agent instructions with the actual company name\n"
                "- Include today's date in all reports\n\n"
                "## Error Handling\n\n"
                "- If no company name can be identified, ask the user to specify a company\n"
                "- If data collection fails, provide specific reasons and retry with modified search terms\n"
                "- If the report is incomplete, identify missing sections and collect additional data\n"
            ),
            model=self.model,
            handoffs=[report_writer, financial_analyst, research_evaluator, research_analyst],
        )
        return root_agent
    

    def invoke_llm(self, query: str) -> Union[Dict[str, Any], str]:
        """
        Run a company research query through the agent system.
        
        Args:
            query (str): The user query about a company to research.
            
        Returns:
            Union[Dict[str, Any], str]: The research results or an error message.
        """
        if not query or not query.strip():
            return "Please provide a valid query with a company name to research."
        
        try:
            # Extract company name from the query
            company_name = self._extract_company_name(query)
            if not company_name:
                return "Could not identify a company name in your query. Please specify which company you would like to research."
            
            # Sanitize input and add company_name to context
            sanitized_query = json.dumps(query)[1:-1]  # Remove outer quotes from JSON string
            
            # Create input with company name context
            input_data = json.dumps({
                "role": "user", 
                "content": sanitized_query,
                "context": {"company_name": company_name}
            })
            
            logger.info(f"Starting research for company: {company_name}")
            
            # Setup asyncio event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Trace the agent's execution for monitoring
            with trace(workflow_name=f"Company Research: {company_name}"):
                # Track execution time
                start_time = datetime.now()
                
                # Run the query through the agent system with company name context
                result: RunResult = self.runner.run_sync(
                    self.root_agent,
                    input=input_data,
                    session=self.session,
                    context={"company_name": company_name}  # Pass company name to context
                )
                
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.info(f"Research for {company_name} completed in {execution_time:.2f} seconds")
                
                # Process the result
                assistant_reply = str(result.final_output)
                
                # Replace any remaining COMPANY_NAME placeholders with the actual company name
                assistant_reply = assistant_reply.replace("COMPANY_NAME", company_name)
                
            return assistant_reply
            
        except Exception as e:
            logger.error(f"Error in company research: {str(e)}", exc_info=True)
            return f"I encountered an error while researching the company. Please try again or rephrase your query. Error: {str(e)}"
