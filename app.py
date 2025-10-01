import streamlit as st
from ui import position, option, chat, transactions, stock_allocation
import logging

# Create and configure logger
logging.basicConfig(
    filename="app.log", format="%(asctime)s %(message)s", filemode="w"
)

# Creating an object
logger = logging.getLogger()

# Setting the threshold of logger to DEBUG
logger.setLevel(logging.DEBUG)

# Set Streamlit page configuration to increase table width
st.set_page_config(layout="wide")
st.title("Options Trading Dashboard")


tab1_view, tab2_view, tab3_view, tab4_view, tab5_view = st.tabs(
    ["Positions", "Market Data", "Chat", "Transactions", "Stock Allocation"]
)

with tab1_view:
    position.render()

with tab2_view:
    option.render()

with tab3_view:
    chat.render()

with tab4_view:
    transactions.render()

with tab5_view:
    stock_allocation.render()
