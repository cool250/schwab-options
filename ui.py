import streamlit as st
from broker.accounts import AccountsTrading
from loguru import logger
import pandas as pd


# Initialize the AccountsTrading class
accounts_trading = AccountsTrading()

def fetch_exposure():
    """
    Fetch the total exposure for short PUT options directly using AccountsTrading.
    """
    securities_account = accounts_trading.get_positions()
    if not securities_account:
        st.error("Securities account not found.")
        return None

    total_exposure = accounts_trading.calculate_total_exposure_for_short_puts(securities_account)
    return total_exposure

# Streamlit UI
st.title("Short PUT Options Exposure")

logger.info("Fetching exposure data...")
data = fetch_exposure()

# Directly use the data dictionary for display
if data:
    total_exposure_data = data
    if isinstance(total_exposure_data, dict):
        # Display the data in a table format
        st.subheader("Exposure by Ticker")
        # Improved table format with Streamlit's dataframe feature
        exposure_table = pd.DataFrame(
            [{"Ticker": ticker, "Exposure ($)": exposure} for ticker, exposure in total_exposure_data.items()]
        )
        st.dataframe(exposure_table.style.format({"Exposure ($)": "${:,.2f}"}))
    else:
        st.error("Invalid format for total_exposure data.")
else:
    st.error("No data received or invalid data structure.")