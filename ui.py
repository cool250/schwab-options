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
securities_account = accounts_trading.get_positions()

def fetch_overall_exposure():
    """
    Fetch the total exposure for short PUT options directly using AccountsTrading.
    """
    if not securities_account:
        st.error("Securities account not found.")
        return None
    total_exposure = accounts_trading.calculate_total_exposure_for_short_puts(securities_account)
    return total_exposure

def fetch_option_positions_details():
    """
    Fetch option positions details directly using AccountsTrading.
    """
    if not securities_account:
        st.error("Securities account not found.")
        return None

    puts = accounts_trading.get_puts(securities_account)
    puts = get_price_position(puts)
    
    calls = accounts_trading.get_calls(securities_account)
    calls = get_price_position(calls)

    return puts, calls

def get_price_position(options):
    """
    Fetch the price position for the given puts and calls.
    """
    price_positions = [option.get("symbol") for option in options if option.get("symbol")]
    logger.debug(f"Option symbols: {price_positions}")
    
    if not price_positions:
        return options

    quote_string = ", ".join(price_positions)
    quotes = market_data.get_stock_quote(quote_string)

    quote_data = {
        symbol: asset.quote.closePrice
        for symbol, asset in quotes.root.items()
        if asset.quote and asset.quote.closePrice is not None
    }

    for option in options:
        symbol = option.get("symbol")
        option["current_price"] = quote_data.get(symbol, 0)

    return options

def get_balances():
    """
    Fetch account balances directly using AccountsTrading.
    """
    if not securities_account:
        st.error("Securities account not found.")
        return None

    balances = accounts_trading.get_balances(securities_account)
    return balances

# Streamlit UI
st.title("Positions")
balance = get_balances()


if balance:
    margin_balance = balance.get('margin', None)
    if margin_balance is not None:
        st.subheader(f"Margin Balance: ${margin_balance:,.2f}")
    else:
        st.error("Margin balance not found in account balances.")
logger.info("Fetching exposure data...")
data = fetch_overall_exposure()

# Directly use the data dictionary for display
if data:
    # Display the data in a table format
    exposure_table = pd.DataFrame(
        [{"Ticker": ticker, "Exposure ($)": exposure} for ticker, exposure in data.items()]
    )
    total_exposure_value = sum(data.values())
    st.header(f"Exposure by Ticker (Total: ${total_exposure_value})")
    st.dataframe(exposure_table.set_index(exposure_table.columns[0]))

else:
    st.error("No data received or invalid data structure.")

option_positions = fetch_option_positions_details()
if option_positions:
    puts, calls = option_positions

if puts:

    # Display the data in a table format
    details_table = pd.DataFrame(puts).reset_index(drop=True)
    if 'expiration_date' in details_table.columns:
        details_table = details_table.sort_values(by='expiration_date')
    st.header("Put Positions")
    st.dataframe(details_table.set_index(details_table.columns[0]))
else:
    st.error("No option positions details found.")

if calls:
    
    # Display the data in a table format
    details_table = pd.DataFrame(calls).reset_index(drop=True)
    if 'expiration_date' in details_table.columns:
        details_table = details_table.sort_values(by='expiration_date')
    st.header("Call Positions")
    st.dataframe(details_table.set_index(details_table.columns[0]))