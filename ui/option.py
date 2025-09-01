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
    with st.form("input_form"):
        # Create two columns
        col1_input, col2_input = st.columns(2)

        # User input for ticker symbol and strike price
        ticker = col1_input.text_input("Enter Ticker Symbol:")
        strike_price = col2_input.number_input("Enter Strike Price:")

        # Date range inputs with calendar picker
        from_date = col1_input.date_input("From Date:", value=datetime.now(pytz.timezone("US/Eastern")))
        to_date = col2_input.date_input("To Date:", value=datetime.now(pytz.timezone("US/Eastern")) + timedelta(days=8))

        get_expirations = st.form_submit_button("Get All Expiration Dates")
           
    max_return = st.button("Max Returns")
    # Button to trigger analysis
    if max_return:
        if ticker and strike_price > 0:
            with st.spinner("Fetching data..."):
                # Convert date objects to strings in the required format
                from_date_str = from_date.strftime("%Y-%m-%d")
                to_date_str = to_date.strftime("%Y-%m-%d")

                result = option_chain_service.highest_return_puts(
                    symbol=ticker,
                    strike=strike_price,
                    from_date=from_date_str,
                    to_date=to_date_str
                )
                if result:
                    max_return, best_expiration_date, price = result
                else:
                    max_return, best_expiration_date, price = None, None, None

            if max_return and best_expiration_date and price:
                st.write(f"Best Expiration Date: {best_expiration_date}")
                st.write(f"Maximum Return: {max_return:.2f}%")
                st.write(f"Option Price: {price:.2f}")
            else:
                st.error("Unexpected result format or no data found.")
        else:
            st.error("Please provide valid inputs.")

    # Button to fetch all expiration dates
    if get_expirations:
        if ticker and strike_price > 0:
            with st.spinner("Fetching data..."):
                # Convert date objects to strings in the required format
                from_date_str = from_date.strftime("%Y-%m-%d")
                to_date_str = to_date.strftime("%Y-%m-%d")

                results = option_chain_service.get_all_expiration_dates(
                    symbol=ticker,
                    strike=strike_price,
                    from_date=from_date_str,
                    to_date=to_date_str
                )

            if results:
                st.write("### Expiration Dates and Returns")
                for result in results:
                    st.write(f"Expiration Date: {result['expiration_date']}, Price: ${result['price']:.2f}, Annualized Return: {result['annualized_return']:.2f}%")
            else:
                st.error("No data found for the given inputs.")
        else:
            st.error("Please provide valid inputs.")