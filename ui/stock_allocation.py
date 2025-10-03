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
            realized_gains_only=False,
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
        col1, col2, col3 = st.columns([2,2,1])
        year = col1.selectbox("Select Year", options=list(range(today.year, today.year-5, -1)), index=0)
        month = col2.selectbox("Select Month", options=list(range(1, 13)), format_func=lambda x: datetime(1900, x, 1).strftime('%B'), index=today.month-1)
        col3.markdown("<div style='height:1.8em;'></div>", unsafe_allow_html=True)
        submitted = col3.form_submit_button("Submit")
    if not submitted:
        return
    with st.spinner("Loading data and charts..."):
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

        col1, col2 = st.columns(2)
        with col1:
            fig = px.pie(
                agg,
                names='underlying_symbol',
                values='total_amount',
                title=f"Stock Allocation for {datetime(year, month, 1).strftime('%B %Y')} with total (${total:,.2f})",
                hole=0.3,
                labels={'underlying_symbol': 'Stock', 'total_amount': 'Amount'},
            )
            fig.update_traces(
                textinfo='label+percent',
                hovertemplate='<b>%{label}</b><br>Amount: $%{value:,.2f}<br>Percent: %{percent:.1%}<extra></extra>'
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], errors='coerce')
                df = df.dropna(subset=['date'])
                df['week'] = df['date'].dt.isocalendar().week
                weekly_agg = df.groupby(['week', 'underlying_symbol'])['total_amount'].sum().reset_index()
                weekly_agg = weekly_agg[weekly_agg['total_amount'] != 0]
                if not weekly_agg.empty:
                    bar_fig = px.bar(
                        weekly_agg,
                        x='week',
                        y='total_amount',
                        color='underlying_symbol',
                        barmode='group',
                        labels={'total_amount': 'Amount ($)', 'week': 'Week', 'underlying_symbol': 'Stock'},
                        title=f"Weekly Stock Allocation for {datetime(year, month, 1).strftime('%B %Y')}"
                    )
                    st.plotly_chart(bar_fig, use_container_width=True)
                else:
                    st.info("No weekly data available for this month.")
            else:
                st.info("No date information available for weekly breakdown.")

        st.dataframe(agg.rename(columns={"total_amount": "Amount ($)", "percent": "Percent (%)"}), hide_index=True)
