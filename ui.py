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


# Initialize the AccountsTrading class
accounts_trading = AccountsTrading()
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
    calls = accounts_trading.get_calls(securities_account)
    return puts, calls

# Streamlit UI
st.title("Short PUT Options Exposure")

logger.info("Fetching exposure data...")
data = fetch_overall_exposure()

# Directly use the data dictionary for display
if data:
    # Display the data in a table format
    st.header("Exposure by Ticker")
    # Improved table format with Streamlit's dataframe feature
    exposure_table = pd.DataFrame(
        [{"Ticker": ticker, "Exposure ($)": exposure} for ticker, exposure in data.items()]
    )
    st.dataframe(exposure_table.set_index(exposure_table.columns[0]))

else:
    st.error("No data received or invalid data structure.")



option_positions = fetch_option_positions_details()
if option_positions:
    puts, calls = option_positions

if puts:
    st.header("Put Positions")
    # Display the data in a table format
    details_table = pd.DataFrame(puts).reset_index(drop=True)
    if 'expiration_date' in details_table.columns:
        details_table = details_table.sort_values(by='expiration_date')
    st.dataframe(details_table.set_index(details_table.columns[0]))
else:
    st.error("No option positions details found.")

if calls:
    st.header("Call Positions")
    # Display the data in a table format
    details_table = pd.DataFrame(calls).reset_index(drop=True)
    if 'expiration_date' in details_table.columns:
        details_table = details_table.sort_values(by='expiration_date')
    st.dataframe(details_table.set_index(details_table.columns[0]))