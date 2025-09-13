from datetime import datetime, timedelta
import pandas as pd
import pytz
import streamlit as st
from service.transactions import TransactionService

def display_ui_table(data, sort_column):
    """
    Helper function to sort and display a table.
    """
    table = pd.DataFrame(data)
    if sort_column in table.columns:
        table = table.sort_values(by=sort_column)
    st.dataframe(table, hide_index=True)

def render():
    transaction_service = TransactionService()
    st.title("Option Transactions")
   
    with st.form("transactions_form"):
        # Create two columns
        col1_input, col2_input, col3_input = st.columns(3)

        # User input for ticker symbol and option type
        stock_ticker = col1_input.text_input("Enter Ticker Symbol:")
        contract_type = col2_input.selectbox("Select Option Type:", ["CALL", "PUT","ALL"], index=2)
        realized_gains_only = col3_input.radio("Realized Gains Only:", ["Yes", "No"], index=0)

        # Date range inputs with calendar picker
        start_date = col1_input.date_input("From Date:", value=datetime.now(pytz.timezone("US/Eastern")) - timedelta(days=30))
        end_date = col2_input.date_input("To Date:", value=datetime.now(pytz.timezone("US/Eastern")) - timedelta(days=1))

        # Convert date objects to strings in the required format
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")


        get_transactions_button = st.form_submit_button("Search Transactions")

        if get_transactions_button:
            with st.spinner("Fetching data..."):
                transactions = transaction_service.get_option_transactions(
                    start_date=start_date_str,
                    end_date=end_date_str,
                    stock_ticker=stock_ticker,
                    contract_type=contract_type,
                    realized_gains_only=(realized_gains_only == "Yes")
                )
            if transactions:
                st.subheader("Transactions")
                st.write(f"Total Records: {len(transactions)}")
                st.write(f"Total Amount: {sum(txn['total_amount'] for txn in transactions):,.2f}")
                display_ui_table(transactions, sort_column="expirationDate")

            else:
                st.error("No transactions found for the given criteria.")