# Options Wheel

Options Wheel is a Python-based trading application that interacts with the Schwab API to manage and analyze options (puts, calls), account positions, balances, and transaction history. It uses `Pydantic` for data validation, `FastAPI` for a REST API layer, `Streamlit` for an interactive dashboard UI, and a React frontend as an alternative web interface.

---

## Features

- Fetch account positions, balances, and option/stock holdings.
- Analyze options chains — best annualized return, all expiration dates, price history.
- Track and match open/close option transactions with realized P&L.
- AI agent for natural-language queries over account data.
- FastAPI REST layer with auto-generated OpenAPI docs.
- Streamlit dashboard (legacy) and a React + Vite frontend.

---

## Project Structure

```
.
├── api/                  # FastAPI layer
│   ├── app.py            # Main FastAPI app (mounts all routers)
│   ├── market.py         # /market routes
│   ├── position.py       # /positions routes
│   ├── transactions.py   # /transactions routes
│   └── agent.py          # /agent routes
├── broker/               # Schwab API client and auth
├── data/                 # Pydantic data models
├── service/              # Business logic (MarketService, PositionService, etc.)
├── tools/                # Agent tools
├── ui/                   # Streamlit UI pages
├── frontend/             # React + Vite frontend
│   └── src/
│       ├── pages/        # MarketData, Positions
│       ├── components/   # Navbar, Spinner
│       └── api/          # Fetch wrappers for FastAPI endpoints
├── app.py                # Streamlit entry point
└── main.py               # Token refresh utility
```

---

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- Node.js 18+ and npm (for the React frontend)

---

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-username/options-wheel.git
   cd options-wheel
   ```

2. **Install Python dependencies**:
   ```bash
   uv sync
   ```

3. **Install frontend dependencies**:
   ```bash
   cd frontend && npm install
   ```

---

## How to Run

### 1. Refresh the Schwab Token (first time / when expired)

```bash
uv run python main.py
```

Paste the redirect URL into the terminal when prompted.

---

### 2. Start the FastAPI Server

```bash
uv run uvicorn api.app:app --reload
```

- API base URL: `http://localhost:8000`
- Interactive docs: `http://localhost:8000/docs`

#### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/market/price/{symbol}` | Current ticker price |
| GET | `/market/history/{symbol}` | Price history |
| GET | `/market/options/best` | Best annualized return for a strike |
| GET | `/market/options/expirations` | All expiration dates for a strike |
| GET | `/positions/` | All positions, balances, and stocks |
| GET | `/positions/balances` | Account balances |
| GET | `/positions/stocks` | Stock / ETF holdings |
| GET | `/positions/options` | Open put and call positions |
| GET | `/positions/exposure` | Total dollar exposure by ticker |
| GET | `/transactions/` | Raw transaction history |
| GET | `/transactions/options` | Matched open/close option transactions |
| POST | `/agent/query` | Natural-language AI agent query |

---

### 3. Start the React Frontend

Requires the FastAPI server to be running (requests are proxied via Vite).

```bash
cd frontend && npm run dev
```

- URL: `http://localhost:3000`
- **Market Data** page: options chain analyzer with live price fetch, expiration tables, and max-return display.
- **Positions** page: account balances, stocks, puts, and calls with one-click refresh.

---

### 4. Start the Streamlit Dashboard (legacy)

```bash
uv run streamlit run app.py
```

- URL: `http://localhost:8501`
