import streamlit as st
from broker.accounts import AccountsTrading
from loguru import logger

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

st.write("This application displays the total exposure for short PUT options.")

logger.debug("Fetching exposure data...")
data = fetch_exposure()

# Directly use the data dictionary for display
if data:
    total_exposure_data = data
    if isinstance(total_exposure_data, dict):
        # Display the data in a table format
        st.subheader("Exposure by Ticker")
        exposure_table = [{"Ticker": ticker, "Exposure": f"${exposure:,.2f}"} for ticker, exposure in total_exposure_data.items()]
        st.table(exposure_table)
    else:
        st.error("Invalid format for total_exposure data.")
else:
    st.error("No data received or invalid data structure.")