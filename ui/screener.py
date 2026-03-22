import streamlit as st
import pandas as pd
import plotly.express as px
from service.screener import (
    run_screener,
    WATCHLIST,
    MIN_IVR,
    DELTA_MIN,
    DELTA_MAX,
    DTE_MIN,
    DTE_MAX,
    MIN_BID,
)


def render():
    st.subheader("Short Put Screener")

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.expander("Screener Filters", expanded=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            watchlist_input = st.text_area(
                "Watchlist (one ticker per line or comma-separated)",
                value="\n".join(WATCHLIST),
                height=160,
            )
            min_ivr = st.slider("Min IV Rank (IVR)", min_value=0, max_value=100, value=int(MIN_IVR), step=5)

        with col2:
            delta_min, delta_max = st.slider(
                "Delta Range (absolute value)",
                min_value=0.05,
                max_value=0.50,
                value=(DELTA_MIN, DELTA_MAX),
                step=0.01,
            )
            min_bid = st.number_input("Min Bid ($)", min_value=0.0, value=MIN_BID, step=0.05, format="%.2f")

        with col3:
            dte_min, dte_max = st.slider(
                "DTE Window",
                min_value=1,
                max_value=120,
                value=(DTE_MIN, DTE_MAX),
                step=1,
            )

    run_button = st.button("Run Screener", type="primary")

    if not run_button:
        return

    # Parse watchlist from text area
    raw = watchlist_input.replace(",", "\n")
    watchlist = [t.strip().upper() for t in raw.splitlines() if t.strip()]
    if not watchlist:
        st.error("Watchlist is empty. Add at least one ticker symbol.")
        return

    # ── Run ───────────────────────────────────────────────────────────────────
    status_text = st.empty()
    progress_bar = st.progress(0)
    scanned: list[str] = []

    def on_progress(symbol: str) -> None:
        scanned.append(symbol)
        status_text.caption(f"Scanning {symbol}… ({len(scanned)}/{len(watchlist)})")
        progress_bar.progress(len(scanned) / len(watchlist))

    with st.spinner("Running screener…"):
        results: pd.DataFrame = run_screener(
            watchlist=watchlist,
            min_ivr=float(min_ivr),
            delta_min=delta_min,
            delta_max=delta_max,
            dte_min=dte_min,
            dte_max=dte_max,
            min_bid=min_bid,
            progress_callback=on_progress,
        )

    progress_bar.empty()
    status_text.empty()

    # ── Results ───────────────────────────────────────────────────────────────
    if results.empty:
        st.info("No candidates passed all filters. Try relaxing the thresholds.")
        return

    # Summary metrics
    mcol1, mcol2, mcol3, mcol4 = st.columns(4)
    mcol1.metric("Candidates", len(results))
    mcol2.metric("Symbols", results["symbol"].nunique())
    mcol3.metric("Best Score", f"{results['score'].max():.4f}")
    mcol4.metric("Avg IVR", f"{results['ivr'].mean():.0f}")

    # Top-10 table
    st.markdown("### Top Candidates")
    display = results.head(20).copy()

    # Format columns for display
    fmt = {
        "score":      "{:.4f}",
        "delta":      "{:.3f}",
        "bid":        "${:.2f}",
        "mid":        "${:.2f}",
        "theta":      "{:.3f}",
        "ivr":        "{:.0f}",
        "iv_pct":     "{:.1f}",
        "otm_pct":    "{:.1f}%",
        "underlying": "${:.2f}",
        "strike":     "${:.2f}",
    }
    for col, fmt_str in fmt.items():
        if col in display.columns:
            display[col] = display[col].apply(
                lambda v: fmt_str.format(v) if pd.notna(v) else ""
            )

    st.dataframe(display, hide_index=True, use_container_width=True)

    # ── Charts ────────────────────────────────────────────────────────────────
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        fig_bar = px.bar(
            results.groupby("symbol")["score"].max().reset_index().sort_values("score", ascending=False),
            x="symbol",
            y="score",
            title="Best Score by Symbol",
            labels={"score": "Score", "symbol": "Symbol"},
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with chart_col2:
        fig_scatter = px.scatter(
            results,
            x="delta",
            y="ivr",
            size="open_int",
            color="symbol",
            hover_data=["expiry", "strike", "bid", "dte", "score"],
            title="Delta vs IVR (bubble = open interest)",
            labels={"delta": "Delta (abs)", "ivr": "IVR"},
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

    # Full results download
    st.download_button(
        label="Download full results as CSV",
        data=results.to_csv(index=False).encode("utf-8"),
        file_name="screener_results.csv",
        mime="text/csv",
    )
