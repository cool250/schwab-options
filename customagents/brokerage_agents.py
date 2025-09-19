from agents import Agent
from customagents.tools import (
    get_ticker_price,
    get_balances,
    get_options_chain,
    get_option_transactions,
)




def initialize_options_chain_agent(model: str) -> Agent:
    options_chain_agent = Agent(
        name="Options Chain Agent",
        instructions=(
            "You are responsible for fetching and displaying options chain data.\n"
            "- If strike price is missing, call 'get_ticker_price' first and pass the response as the strike price.\n"
            "- Ensure start_date >= today (default today).\n"
            "- Ensure end_date >= start_date (default +30 days).\n"
            "- Always separate Calls and Puts into two tables.\n"
            "- Tables must include expiration date, strike, price, and annualized return.\n"
            "- Never mix text and function calls in one response.\n"
        ),
        model=model,
        tools=[get_ticker_price, get_options_chain],
    )

    return options_chain_agent


def initialize_balances_agent(model: str) -> Agent:
    balances_agent = Agent(
        name="Balances Agent",
        instructions=(
            "Fetch account balances only when explicitly requested.\n"
            "- Always return structured JSON or a readable table.\n"
            "- Do not add invented metrics.\n"
        ),
        model=model,
        tools=[get_balances],
    )

    return balances_agent


def initialize_transactions_agent(model: str) -> Agent:
    transactions_agent = Agent(
        name="Transactions Agent",
        instructions=(
            "Fetch option transactions.\n"
            "- Default date range: last 30 days.\n"
            "- Default ticker: blank (all tickers).\n"
            "- Default contract type: ALL.\n"
            "- Default realized_gains_only: True.\n"
            "- Always return a table (date, ticker, type, P/L).\n"
            "- Do not ask for more input if defaults are applied.\n"
        ),
        model=model,
        tools=[get_option_transactions],
    )
    return transactions_agent
