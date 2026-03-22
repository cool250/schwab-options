import streamlit as st
from ui import market_data, position, chat, transactions, stock_allocation, screener
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _setup_logging() -> None:
    """Configure application-wide logging.

    Safe to call on every Streamlit rerun — handlers are only attached once.
    - app.log  : all application logs (DEBUG+), rotated at 5 MB, 3 backups
    - api.log  : broker / API calls only (DEBUG+), rotated at 5 MB, 3 backups
    - stderr   : WARNING+ for quick visibility in the terminal
    """
    LOG_DIR = Path(__file__).parent / "logs"
    LOG_DIR.mkdir(exist_ok=True)

    SHARED_FMT = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    CONSOLE_FMT = logging.Formatter("%(levelname)-8s %(name)s - %(message)s")

    root = logging.getLogger()

    # ── Guard: only configure once per process ────────────────────────────────
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)

    # app.log — all loggers in this project
    app_handler = RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(SHARED_FMT)
    root.addHandler(app_handler)

    # stderr — WARNING and above so the terminal isn't flooded
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(CONSOLE_FMT)
    root.addHandler(console_handler)

    # api.log — broker package only; propagate=False keeps entries out of app.log
    api_handler = RotatingFileHandler(
        LOG_DIR / "api.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    api_handler.setLevel(logging.DEBUG)
    api_handler.setFormatter(SHARED_FMT)
    broker_logger = logging.getLogger("broker")
    broker_logger.setLevel(logging.DEBUG)
    broker_logger.addHandler(api_handler)
    broker_logger.propagate = False  # don't duplicate into app.log

    # Silence noisy third-party libraries
    for noisy in ("urllib3", "httpx", "httpcore", "streamlit", "watchdog"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_setup_logging()

# Set Streamlit page configuration to increase table width
st.set_page_config(layout="wide")
st.title("Options Trading Dashboard")


tab1_view, tab2_view, tab3_view, tab4_view, tab5_view, tab6_view = st.tabs(
    ["Positions", "Market Data", "Chat", "Transactions", "Stock Allocation", "Screener"]
)

with tab1_view:
    position.render()

with tab2_view:
    market_data.render()

with tab3_view:
    chat.render()

with tab4_view:
    transactions.render()

with tab5_view:
    stock_allocation.render()

with tab6_view:
    screener.render()
