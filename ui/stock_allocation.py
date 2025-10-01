import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
from service.transactions import TransactionService

def fetch_stock_transactions(year: int, month: int):
    # Get the first and last day of the month
    start_date = datetime(year, month, 1).strftime("%Y-%m-%d")
    if month == 12:
        end_date = datetime(year + 1, 1, 1) - pd.Timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1) - pd.Timedelta(days=1)
    end_date = end_date.strftime("%Y-%m-%d")
    # Use 'ALL' to get all stocks
    stock_ticker = ""
    try:
        service = TransactionService()
        data = service.get_option_transactions(
            start_date=start_date,
            end_date=end_date,
            contract_type="ALL",
            realized_gains_only=True,
            stock_ticker=stock_ticker
        )
        return data
    except Exception as e:
        st.error(f"Failed to fetch transactions: {e}")
        return []

def render():
    st.header("Monthly Gains")
    today = datetime.today()
    with st.form("stock_allocation_form"):
        year = st.selectbox("Select Year", options=list(range(today.year, today.year-5, -1)), index=0)
        month = st.selectbox("Select Month", options=list(range(1, 13)), format_func=lambda x: datetime(1900, x, 1).strftime('%B'), index=today.month-1)
        submitted = st.form_submit_button("Submit")
    if not submitted:
        return
    data = fetch_stock_transactions(year, month)
    if not data:
        st.info("No transaction data available for this month.")
        return
    df = pd.DataFrame(data)
    # Filter for stock transactions only (type == 'STOCK')
    if df.empty or 'underlying_symbol' not in df.columns or 'total_amount' not in df.columns:
        st.info("No stock transaction data for this month.")
        return
    # Aggregate by symbol
    agg = df.groupby('underlying_symbol')['total_amount'].sum().reset_index()
    agg = agg[agg['total_amount'] != 0]
    if agg.empty:
        st.info("No stock allocation for this month.")
        return
    total = agg['total_amount'].sum()
    agg['percent'] = agg['total_amount'] / total * 100
    st.markdown(f"**Total Allocation:** ${total:,.2f}")
    st.dataframe(agg.rename(columns={"total_amount": "Amount ($)", "percent": "Percent (%)"}), hide_index=True)
    fig = px.pie(
        agg,
        names='underlying_symbol',
        values='total_amount',
        title=f"Stock Allocation for {datetime(year, month, 1).strftime('%B %Y')}",
        hole=0.3,
        labels={'underlying_symbol': 'Stock', 'total_amount': 'Amount'},
    )
    fig.update_traces(
        textinfo='label+percent',
        hovertemplate='<b>%{label}</b><br>Amount: $%{value:,.2f}<br>Percent: %{percent:.1%}<extra></extra>'
    )
    st.plotly_chart(fig, use_container_width=True)
