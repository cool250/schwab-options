# Options Wheel

Options Wheel is a Python-based trading application that interacts with the Schwab API to manage and analyze options (puts, calls), account positions, balances, and transaction history. It uses `Pydantic` for data validation, `FastAPI` for a REST API layer, and a React + Vite frontend for the dashboard UI.

---

## Features

- Fetch account positions, balances, and option/stock holdings.
- Analyze options chains — best annualized return, all expiration dates, price history.
- Track and match open/close option transactions with realized P&L.
- AI agent for natural-language queries over account data.
- FastAPI REST layer with auto-generated OpenAPI docs.
- React + Vite frontend dashboard.

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
├── frontend/             # React + Vite frontend
│   └── src/
│       ├── pages/        # MarketData, Positions
│       ├── components/   # Navbar, Spinner
│       └── api/          # Fetch wrappers for FastAPI endpoints
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
| GET | `/api/market/price/{symbol}` | Current ticker price |
| GET | `/api/market/history/{symbol}` | Price history |
| GET | `/api/market/options/best` | Best annualized return for a strike |
| GET | `/api/market/options/expirations` | All expiration dates for a strike |
| GET | `/api/positions/` | All positions, balances, and stocks |
| GET | `/api/positions/balances` | Account balances |
| GET | `/api/positions/stocks` | Stock / ETF holdings |
| GET | `/api/positions/options` | Open put and call positions |
| GET | `/api/positions/exposure` | Total dollar exposure by ticker |
| GET | `/api/transactions/` | Raw transaction history |
| GET | `/api/transactions/options` | Matched open/close option transactions |
| POST | `/api/agent/query` | Natural-language AI agent query |

---

### 3. Start the React Frontend

Requires the FastAPI server to be running (requests are proxied via Vite).

```bash
cd frontend && npm run dev
```

- URL: `http://localhost:3000`
- **Market Data** page: options chain analyzer with live price fetch, expiration tables, and max-return display.
- **Positions** page: account balances, stocks, puts, and calls with one-click refresh.
- **Transactions** page: filter and browse option transactions with realized P&L.
- **Monthly Gains** page: allocation breakdown by symbol with pie and bar charts.

---

## Deploying to Heroku

The app uses a **single web dyno**: FastAPI serves both the REST API and the pre-built React frontend from `frontend/dist/`.

### Prerequisites

- [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli) installed and logged in
- Git repo initialised

### One-time setup

```bash
# Create the app
heroku create your-app-name

# Two buildpacks: Node (builds React) then Python (runs FastAPI)
heroku buildpacks:add --index 1 heroku/nodejs
heroku buildpacks:add --index 2 heroku/python
```

### Set environment variables

| Variable | Required | Description |
|---|---|---|
| `APP_KEY` | Yes | Schwab API app key |
| `APP_SECRET` | Yes | Schwab API app secret |
| `APP_CALLBACK_URL` | Yes | OAuth redirect URI registered in Schwab developer portal |
| `OPENAI_API_KEY` | Yes | OpenAI API key for the AI agent |
| `SERPAPI_API_KEY` | Yes | SerpAPI key for web search in the AI agent |
| `SECRET_KEY` | Yes | Secret key for signing JWT session tokens |
| `ADMIN_USERNAME` | Yes | Login username for the dashboard |
| `ADMIN_PASSWORD` | Yes | Login password for the dashboard |
| `TOKEN_JSON` | Yes | Full Schwab OAuth token as a single-line JSON string (initial seed) |
| `USE_DB` | No | Set to `true` to store the token in Redis instead of the env var |
| `REDIS_URL` | If `USE_DB=true` | Redis connection URL (set automatically by the Heroku Redis addon) |

```bash
heroku config:set APP_KEY=...
heroku config:set APP_SECRET=...
heroku config:set APP_CALLBACK_URL=https://your-app.herokuapp.com/callback
heroku config:set OPENAI_API_KEY=...
heroku config:set SERPAPI_API_KEY=...
heroku config:set SECRET_KEY=...
heroku config:set ADMIN_USERNAME=...
heroku config:set ADMIN_PASSWORD=...

# Paste the full token.json contents as a single-line JSON string
heroku config:set TOKEN_JSON="$(python -c "import json; print(json.dumps(json.load(open('token.json'))))")"

# Optional: enable Redis token storage
heroku config:set USE_DB=true
```

> **Token expiry**: Schwab tokens expire every 7 days. Re-run `uv run python main.py` locally, then update `TOKEN_JSON` on Heroku with the command above.

### Updating the Schwab token on Heroku manually

Schwab's OAuth tokens must be refreshed before they expire (every 7 days).

**Step 1 — Refresh locally**
```bash
uv run python main.py
```

**Step 2 — Push the new token to Heroku**
```bash
heroku config:set TOKEN_JSON="$(python -c "import json; print(json.dumps(json.load(open('token.json'))))")" --app your-app-name
```

Heroku restarts the dyno automatically after the config var is updated.

**Verify it was set:**
```bash
heroku config:get TOKEN_JSON --app your-app-name
```

**Check the token expiry locally:**
```bash
python -c "import json; d=json.load(open('token.json')); print(d.get('expires_in'), 'seconds')"
```

### Deploy

```bash
git push heroku main
```

Heroku will:
1. Run `npm install && npm run build` inside `frontend/` (Node.js buildpack → `heroku-postbuild`).
2. Install Python dependencies from `requirements.txt` (Python buildpack).
3. Start the web dyno via `Procfile`: `uvicorn api.app:app --host 0.0.0.0 --port $PORT`.

- API: `https://your-app.herokuapp.com/api/...`
- OpenAPI docs: `https://your-app.herokuapp.com/docs`
- React app: `https://your-app.herokuapp.com/`

---

## Token Storage

The app supports two backends for storing the Schwab OAuth token, controlled by the `USE_DB` environment variable.

| `USE_DB` | Backend | When to use |
|---|---|---|
| `false` / unset | `token.json` file (or `TOKEN_JSON` env var) | Local development |
| `true` | Redis (`REDIS_URL`) | Production / Heroku |

### Local development (default — no Redis needed)

Token is read from `token.json` in the project root. No extra configuration required.

### Local development with Redis

```bash
# Start Redis
brew services start redis

# Seed Redis with your current token
python3 -c "
import json, redis
r = redis.from_url('redis://localhost:6379', decode_responses=True)
r.set('TOKEN_JSON', open('token.json').read())
print('Token seeded to Redis')
"
```

Add to `.env`:
```
USE_DB=true
REDIS_URL=redis://localhost:6379
```

### Heroku (Redis)

```bash
# Add the Redis addon (sets REDIS_URL automatically)
heroku addons:create heroku-redis:mini --app your-app-name

# Enable Redis storage
heroku config:set USE_DB=true --app your-app-name

# Seed the token into Redis (one-time / after each 7-day Schwab expiry)
heroku run python3 -c "
import json, os, redis
r = redis.from_url(os.environ['REDIS_URL'], decode_responses=True)
token = os.environ['TOKEN_JSON']
r.set('schwab_token', token)
print('Token seeded')
" --app your-app-name
```

After seeding, tokens are automatically refreshed in Redis on every `401` response — no manual re-seeding needed until the refresh token itself expires (~7 days).
