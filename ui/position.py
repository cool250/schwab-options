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

Usage:
1. Ensure the Streamlit server is running.
2. View the application in your browser at the provided URL (usually `http://localhost:8502`).
"""

import streamlit as st
import pandas as pd

from service.position import PositionService

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
    st.dataframe(table, hide_index=True)

# Streamlit UI

def render():

    
    # # Add a refresh link at the top of the page
    if st.button("Refresh Data"):
        # The service class to provide all data
        service = PositionService()

        # Fetch data from the service
        option_positions, exposure, balance, stocks = service.populate_positions()

        # Display balances
        if balance:
            margin = balance.get("margin")
            mutualFundValue = balance.get("mutualFundValue")
            account = balance.get("account")
            # Display balances in a single row as columns
            col1, col2, col3 = st.columns(3)
            if margin is not None:
                col1.metric("Margin Balance", f"${margin:,.2f}")
            if mutualFundValue is not None:
                col2.metric("Mutual Fund", f"${mutualFundValue:,.2f}")
            if account is not None:
                col3.metric("Account Value", f"${account:,.2f}")
            else:
                handle_error("Margin balance not found in account balances.")

        # Display stocks
        if stocks:
            st.subheader("Stocks")
            display_ui_table(stocks, "ticker")
        else:
            handle_error("No stocks found.")

        # Display option positions
        if option_positions:
            puts, calls = option_positions

            if puts:
                st.subheader("Put")
                display_ui_table(puts, "expiration_date")
            else:
                handle_error("No PUT option positions found.")

            if calls:
                st.subheader("Call")
                display_ui_table(calls, "expiration_date")
            else:
                handle_error("No CALL option positions found.")

        # Display overall exposure
        if exposure:
            exposure_list = [{"Ticker": ticker, "Exposure ($)": exposure} for ticker, exposure in exposure.items()] # convert dict to list of dicts
            st.subheader("Exposure")
            st.metric(label="Total Exposure", value=f"${sum(exposure.values()):,.2f}")
            display_ui_table(exposure_list, "Ticker")
        else:
            handle_error("No data received or invalid data structure.")