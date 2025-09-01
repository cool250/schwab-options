from datetime import datetime, timedelta
from unittest import result
import pytz
import streamlit as st
from service.option_chain import OptionChainService

# Initialize the OptionChainService
option_chain_service = OptionChainService()
def render():
    # Streamlit app title
    st.subheader("Options Chain Analyzer")

    # Create two columns
    col1_input, col2_input = st.columns(2)

    # User input for ticker symbol and strike price
    ticker = col1_input.text_input("Enter Ticker Symbol:")
    strike_price = col2_input.number_input("Enter Strike Price:")

    # Date range inputs
    et_timezone = pytz.timezone("US/Eastern")
    from_date = (datetime.now(et_timezone)).strftime("%Y-%m-%d")
    to_date = (datetime.now(et_timezone) + timedelta(days=8)).strftime("%Y-%m-%d")

    # Button to trigger analysis
    if st.button("Analyze"):
        if ticker and strike_price > 0:
            with st.spinner("Fetching data..."):
                result = option_chain_service.highest_return_puts(
                    symbol=ticker,
                    strike=strike_price,
                    from_date=from_date,
                    to_date=to_date
                )
                if result:
                    max_return, best_expiration_date, price = result
                else:
                    max_return, best_expiration_date, price = None, None, None

            if max_return and best_expiration_date and price:
                st.success(f"Best Expiration Date: {best_expiration_date}")
                st.success(f"Maximum Return: {max_return:.2f}%")
                st.success(f"Option Price: {price:.2f}")
            else:
                st.error("Unexpected result format or no data found.")
        else:
            st.error("Please provide valid inputs.")

    # Button to fetch all expiration dates
    if st.button("Get All Expiration Dates"):
        if ticker and strike_price > 0:
            with st.spinner("Fetching data..."):
                results = option_chain_service.get_all_expiration_dates(
                    symbol=ticker,
                    strike=strike_price,
                    from_date=from_date,
                    to_date=to_date
                )

            if results:
                st.write("### Expiration Dates and Returns")
                for result in results:
                    st.write(f"Expiration Date: {result['expiration_date']}, Price: ${result['price']:.2f}, Annualized Return: {result['annualized_return']:.2f}%")
            else:
                st.error("No data found for the given inputs.")
        else:
            st.error("Please provide valid inputs.")