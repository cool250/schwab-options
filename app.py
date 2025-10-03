import streamlit as st
from ui import position, option, chat, transactions, stock_allocation
import logging
import sys

# Remove any existing handlers
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# File handler for DEBUG and INFO
file_handler = logging.FileHandler("app.log", mode="w")
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
file_handler.setFormatter(file_formatter)

# Console handler for ERROR and above
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.ERROR)
console_formatter = logging.Formatter("%(levelname)s: %(message)s")
console_handler.setFormatter(console_formatter)

# Add handlers to root logger
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

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
