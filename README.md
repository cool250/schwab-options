# Schwab Options

Schwab Options is a Python-based project that interacts with the Schwab API to fetch account details, transactions, and other trading-related data. It uses `Pydantic` for data validation, `Loguru` for logging, and `python-dotenv` for managing environment variables.

---

## Features

- Fetch account hash values from the Schwab API.
- Retrieve and parse transactions for a given date range.
- Validate API responses using `Pydantic` models.
- Log detailed information about transactions and transfer items.

---

## Prerequisites

Before you begin, ensure you have the following installed:

- Python 3.8 or higher
- `pip` (Python package manager)

---

## Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-username/schwab-options.git
   cd schwab-options
   ```

---

## How to Start the API and UI Layers

### Start the FastAPI Server

1. Navigate to the project directory and run the following command to start the FastAPI server:
   ```bash
   uvicorn api:app --reload
   ```
2. The API will be available at `http://127.0.0.1:8000`.

### Start the Streamlit UI
1. Navigate to the project directory and run the following command to start the Streamlit UI:
   ```bash
   streamlit run ui.py
   ```
2. The UI will be available in your browser at the URL provided by Streamlit (usually `http://localhost:8501`).
