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

    option_positions_details = accounts_trading.get_option_positions_details(securities_account)
    return option_positions_details

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

st.header("Option Positions Details")

option_data = fetch_option_positions_details()
if option_data:
    # Display the data in a table format
    details_table = pd.DataFrame(option_data).reset_index(drop=True)
    if 'expiration_date' in details_table.columns:
        details_table = details_table.sort_values(by='expiration_date')
    st.dataframe(details_table.set_index(details_table.columns[0]))
else:
    st.error("No option positions details found.")