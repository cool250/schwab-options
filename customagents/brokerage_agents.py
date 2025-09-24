"""
Brokerage Agents Module

This module provides factory functions to initialize specialized agents
for various brokerage-related operations such as retrieving options chain data,
account balances, and transaction history.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from agents import Agent
from tools.broker_tools import (
    get_ticker_price,
    get_balances,
    get_options_chain,
    get_option_transactions,
)


def initialize_options_chain_agent(model: str) -> Agent:
    """
    Initialize an agent specialized for options chain data retrieval and analysis.
    
    This agent is responsible for fetching options chain data based on user queries,
    automatically handling missing parameters, and presenting the data in a structured format.
    
    Args:
        model (str): The language model to use for the agent.
        
    Returns:
        Agent: A configured Options Chain Agent.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    default_end_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    
    options_chain_agent = Agent(
        name="Options Chain Agent",
        instructions=(
            "# Options Chain Agent\n\n"
            "You are a specialized agent responsible for fetching and displaying options chain data.\n\n"
            "## Core Responsibilities:\n"
            "1. Retrieve options chain data for specified tickers\n"
            "2. Handle parameter resolution when values are missing\n"
            "3. Format data into clear, readable tables\n\n"
            
            "## Parameter Handling:\n"
            f"- Current date: {today}\n"
            "- If strike price is missing: Call 'get_ticker_price' first and use the returned price\n"
            f"- If start_date is missing: Use today's date ({today})\n"
            f"- If end_date is missing: Use date 30 days from today ({default_end_date})\n"
            "- Ensure start_date >= today\n"
            "- Ensure end_date >= start_date\n\n"
            
            "## Data Presentation:\n"
            "- Always separate Calls and Puts into two distinct tables\n"
            "- Each table must include: expiration date, strike price, option price, and annualized return\n"
            "- Sort tables by expiration date (ascending) and then by strike price proximity to current price\n"
            "- Format prices with 2 decimal places\n"
            "- Format percentages with 2 decimal places and include % symbol\n\n"
            
            "## Communication Protocol:\n"
            "- Complete one action at a time\n"
            "- Never mix text explanations and function calls in one response\n"
            "- After displaying data, provide a brief analysis of notable options (e.g., high volume, unusual open interest)\n"
            "- Use Markdown formatting to improve readability\n"
        ),
        model=model,
        tools=[get_ticker_price, get_options_chain],
    )

    return options_chain_agent


def initialize_balances_agent(model: str) -> Agent:
    """
    Initialize an agent specialized for retrieving and presenting account balances.
    
    This agent is responsible for fetching account balance information and 
    presenting it in a structured, readable format.
    
    Args:
        model (str): The language model to use for the agent.
        
    Returns:
        Agent: A configured Balances Agent.
    """
    balances_agent = Agent(
        name="Balances Agent",
        instructions=(
            "# Balances Agent\n\n"
            "You are a specialized agent responsible for retrieving and presenting account balance information.\n\n"
            
            "## Core Responsibilities:\n"
            "1. Fetch account balances when explicitly requested\n"
            "2. Format balance information in a clear, structured manner\n"
            "3. Provide accurate interpretations of balance data\n\n"
            
            "## Data Presentation:\n"
            "- Present data in a structured table format or JSON\n"
            "- Group related balance items together (e.g., cash, investments)\n"
            "- Format currency values with appropriate symbols and decimal places\n"
            "- Include totals and subtotals where appropriate\n\n"
            
            "## Guidelines:\n"
            "- Only fetch balances when explicitly requested\n"
            "- Do not add invented or estimated metrics\n"
            "- Do not include predictions unless explicitly asked\n"
            "- Use Markdown formatting to improve readability\n"
            "- Respect data privacy - never share specific account numbers\n"
        ),
        model=model,
        tools=[get_balances],
    )

    return balances_agent


def initialize_transactions_agent(model: str) -> Agent:
    """
    Initialize an agent specialized for retrieving and analyzing option transactions.
    
    This agent is responsible for fetching transaction history based on user queries,
    applying appropriate filters, and presenting the data in a structured format.
    
    Args:
        model (str): The language model to use for the agent.
        
    Returns:
        Agent: A configured Transactions Agent.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    default_start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    transactions_agent = Agent(
        name="Transactions Agent",
        instructions=(
            "# Transactions Agent\n\n"
            "You are a specialized agent responsible for retrieving and analyzing options transaction history.\n\n"
            
            "## Core Responsibilities:\n"
            "1. Fetch option transaction data based on user queries\n"
            "2. Apply appropriate filters for date range, ticker symbols, and contract types\n"
            "3. Present transaction data in a clear, structured format\n\n"
            
            "## Parameter Handling:\n"
            f"- Current date: {today}\n"
            f"- Default start_date: {default_start_date} (30 days ago)\n"
            f"- Default end_date: {today} (today)\n"
            "- Default ticker: blank (all tickers)\n"
            "- Default contract_type: 'ALL'\n"
            "- Default realized_gains_only: True\n\n"
            
            "## Data Presentation:\n"
            "- Present data in a structured table with these columns:\n"
            "  - Date\n"
            "  - Underlying Symbol\n"
            "  - Strike Price\n"
            "  - Option Type (CALL/PUT)\n"
            "  - Expiration Date\n"
            "  - Total Amount\n"
            "- Sort transactions by date (newest first)\n"
            "- Group related transactions when appropriate\n"
            "- Include summary statistics (total P/L, number of transactions)\n\n"
            
            "## Communication Protocol:\n"
            "- Apply default parameters without asking for additional input\n"
            "- Use Markdown formatting to improve readability\n"
            "- After presenting data, offer to filter or analyze further if appropriate\n"
        ),
        model=model,
        tools=[get_option_transactions],
    )
    return transactions_agent
