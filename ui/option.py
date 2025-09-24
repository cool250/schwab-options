from datetime import datetime, timedelta
import pandas as pd
import pytz
import streamlit as st
from service.market import MarketService

def render():
    # Streamlit app title
    
    st.subheader("Options Chain Analyzer")

    with st.form("input_form"):
        # Create two columns
        col1_input, col2_input,col3_input = st.columns(3)

        # User input for ticker symbol and strike price
        ticker = col1_input.text_input("Enter Ticker Symbol:")
        strike_price = col2_input.number_input("Enter Strike Price:")
        option_type = col3_input.selectbox("Select Option Type:", ["CALL", "PUT"], index=1)


        # Date range inputs with calendar picker
        from_date = col1_input.date_input("From Date:", value=datetime.now(pytz.timezone("US/Eastern")))
        to_date = col2_input.date_input("To Date:", value=datetime.now(pytz.timezone("US/Eastern")) + timedelta(days=8))

        # Convert date objects to strings in the required format
        from_date_str = from_date.strftime("%Y-%m-%d")
        to_date_str = to_date.strftime("%Y-%m-%d")

        col1_button, col2_button = st.columns(2)
        get_expirations_button = col1_button.form_submit_button("Expiration Dates")
        max_return_button = col2_button.form_submit_button("Max Return")
    # Button to trigger analysis
    if max_return_button:
        market_data_service = MarketService()
        if ticker and strike_price > 0:
            with st.spinner("Fetching data..."):
                result = market_data_service.highest_return(
                    symbol=ticker,
                    strike=strike_price,
                    from_date=from_date_str,
                    to_date=to_date_str,
                    contract_type=option_type
                )
                if result:
                    max_return, best_expiration_date, price = result
                else:
                    max_return, best_expiration_date, price = None, None, None

                ticker_price = market_data_service.get_ticker_price(ticker)

            if max_return and best_expiration_date and price:
                st.write(f"Best Expiration Date: {best_expiration_date}")
                st.write(f"Maximum Return: {max_return:.2f}%")
                st.write(f"Option Price: {price:.2f}")
            else:
                st.error("Unexpected result format or no data found.")
        else:
            st.error("Please provide valid inputs.")

    # Button to fetch all expiration dates
    if get_expirations_button:
        market_data_service = MarketService()
        if ticker and strike_price > 0:
            with st.spinner("Fetching data..."):
                results = market_data_service.get_all_expiration_dates(
                    symbol=ticker,
                    strike=strike_price,
                    from_date=from_date_str,
                    to_date=to_date_str,
                    contract_type=option_type
                )
                current = market_data_service.get_ticker_price(ticker)

            if results:
                # Display results in a table
                st.write(f"### {option_type} Returns for {ticker} at current price {current:.2f}")
                data = {
                    "Expiration": [result['expiration_date'] for result in results],
                    "Strike ($)": [f"{result['strike']:.2f}" for result in results],
                    "Price ($)": [f"{result['price']:.2f}" for result in results],
                    "Annualized Return (%)": [f"{result['annualized_return']:.2f}" for result in results]
                }
                table = pd.DataFrame(data)
                st.table(table.set_index(table.columns[0]))
            else:
                st.error("No data found for the given inputs.")
        else:
            st.error("Please provide valid inputs.")

    st.markdown("</div>", unsafe_allow_html=True)