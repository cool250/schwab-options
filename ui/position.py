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
from service.position import PositionService


# The service class to provide all data
service = PositionService()

# Helper function to handle errors and return data
def handle_error(message):
    st.error(message)
    return None

def display_ui_table(data, sort_column):
    """
    Helper function to sort and display a table.
    """
    table = pd.DataFrame(data)
    if sort_column in table.columns:
        table = table.sort_values(by=sort_column)
    st.dataframe(table.set_index(table.columns[0]))


option_positions, exposure, balance = service.populate_positions()
# Streamlit UI

def render():

    # Display balances
    if balance:
        margin_balance = balance.get("margin")
        if margin_balance is not None:
            st.text(f"Margin Balance: ${margin_balance:,.2f}")
        else:
            handle_error("Margin balance not found in account balances.")

    # Display overall exposure
    if exposure:
        exposure_list = [{"Ticker": ticker, "Exposure ($)": exposure} for ticker, exposure in exposure.items()] # convert dict to list of dicts
        st.subheader("Exposure by Ticker")
        st.text(f"Total Exposure: ${sum(exposure.values()):,.2f}")
        display_ui_table(exposure_list, "Ticker")
    else:
        handle_error("No data received or invalid data structure.")

    # Display option positions
    if option_positions:
        puts, calls = option_positions

        if puts:
            st.header("Put Positions")
            display_ui_table(puts, "expiration_date")
        else:
            handle_error("No PUT option positions found.")

        if calls:
            st.header("Call Positions")
            display_ui_table(calls, "expiration_date")
        else:
            handle_error("No CALL option positions found.")