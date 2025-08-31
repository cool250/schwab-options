import streamlit as st
import ui.position as position

st.title("Options Trading Dashboard")

tab1_view, tab2_view = st.tabs(["Positions", "Market Data"])

# Set Streamlit page configuration to increase table width
st.set_page_config(layout="wide")

with tab1_view:
    position.render()

with tab2_view:
    st.header("Market Data")