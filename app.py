import streamlit as st
from ui import position, option

st.title("Options Trading Dashboard")

tab1_view, tab2_view = st.tabs(["Positions", "Market Data"])

# Set Streamlit page configuration to increase table width
st.set_page_config(layout="wide")

with tab1_view:
    position.render()

with tab2_view:
    option.render()