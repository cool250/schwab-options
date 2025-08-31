"""
Streamlit Application: Short PUT Options Exposure

This application provides a user interface to display the total exposure for short PUT options
and detailed option positions fetched directly from the `AccountsTrading` class.

Features:
- Displays overall exposure by ticker.
- Provides detailed option positions with sorting and filtering capabilities.
- Utilizes Streamlit for an interactive and user-friendly experience.

Modules:
- `AccountsTrading`: Handles fetching and processing of account and position data.
- `pandas`: Used for data manipulation and display in tabular format.
- `loguru`: Provides logging for debugging and information tracking.

Usage:
1. Ensure the Streamlit server is running.
2. View the application in your browser at the provided URL (usually `http://localhost:8502`).
"""

import streamlit as st
from broker.accounts import AccountsTrading
from loguru import logger
import pandas as pd

from broker.market_data import MarketData


# Set Streamlit page configuration to increase table width
st.set_page_config(layout="wide")

# Initialize the AccountsTrading class
accounts_trading = AccountsTrading()
market_data = MarketData()

# Fetch the securities account
securities_account = accounts_trading.get_positions()

# Helper function to handle errors and return data
def handle_error(message):
    st.error(message)
    return None

def display_table(data, sort_column):
    """
    Helper function to display a sorted table.
    """
    table = pd.DataFrame(data).reset_index(drop=True)
    if sort_column in table.columns:
        table = table.sort_values(by=sort_column)
    st.dataframe(table.set_index(table.columns[0]))

def fetch_overall_exposure():
    """
    Fetch the total exposure for short PUT options directly using AccountsTrading.
    """
    if not securities_account:
        return handle_error("Securities account not found.")
    return accounts_trading.calculate_total_exposure_for_short_puts(securities_account)

def fetch_option_positions_details():
    """
    Fetch option positions details directly using AccountsTrading.
    """
    if not securities_account:
        return handle_error("Securities account not found.")

    puts = get_current_price(accounts_trading.get_puts(securities_account))
    calls = get_current_price(accounts_trading.get_calls(securities_account))
    return puts, calls

def get_current_price(options):
    """
    Fetch the price position for the given options.
    """
    price_positions = [option.get("symbol") for option in options if option.get("symbol")]

    if not price_positions: # should ideally not be empty
        return options

    # Pass all symbols to market data as comma separated values
    quotes = market_data.get_price(", ".join(price_positions))
    quote_data = {}
    if quotes and hasattr(quotes, "root"):
        quote_data = {
            symbol: asset.quote.closePrice
            for symbol, asset in quotes.root.items()
            if asset.quote and asset.quote.closePrice is not None
        }

    for option in options:
        current_price = quote_data.get(option.get("symbol"), 0)
        option["current_price"] = f"${current_price:,.2f}"

    return options

def get_balances():
    """
    Fetch account balances directly using AccountsTrading.
    """
    if not securities_account:
        return handle_error("Securities account not found.")
    return accounts_trading.get_balances(securities_account)

# Streamlit UI
st.title("Positions")

# Display balances
balance = get_balances()
if balance:
    margin_balance = balance.get("margin")
    if margin_balance is not None:
        st.subheader(f"Margin Balance: ${margin_balance:,.2f}")
    else:
        handle_error("Margin balance not found in account balances.")

# Display overall exposure
data = fetch_overall_exposure()
if data:
    exposure_table = pd.DataFrame(
        [{"Ticker": ticker, "Exposure ($)": exposure} for ticker, exposure in data.items()]
    )
    st.subheader(f"Exposure by Ticker (Total: ${sum(data.values()):,.2f})")
    st.dataframe(exposure_table.set_index("Ticker"))
else:
    handle_error("No data received or invalid data structure.")



# Display option positions
option_positions = fetch_option_positions_details()
if option_positions:
    puts, calls = option_positions

    if puts:
        st.header("Put Positions")
        display_table(puts, "expiration_date")
    else:
        handle_error("No PUT option positions found.")

    if calls:
        st.header("Call Positions")
        display_table(calls, "expiration_date")
    else:
        handle_error("No CALL option positions found.")