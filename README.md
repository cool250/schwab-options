# Options Wheel

Options Wheel is a Python-based trading dashboard for running an options-wheel strategy against a real brokerage account. It's a single-user personal app: FastAPI backend, React + Vite frontend, backed by the Schwab API (positions, balances, transaction history — always read-only, no order placement exists anywhere in this app) and Tastytrade (live option chains, streaming quotes via DXLink). It also ships a read-only AI "Copilot" chat for asking questions about your own account and market data.

For a deeper architectural tour (service layer, broker clients, copilot subsystem, frontend conventions), see [`AGENTS.md`](./AGENTS.md). This README is the practical "get it running" guide.

---

## Features

- Account positions, balances, and stock/ETF holdings, plus derived futures and futures-option positions (Schwab's positions API doesn't return either, so those are reconstructed from transaction history).
- Options chain browser and payoff/P&L analyzer ("Analyze" / StrikeLab) — live chain streaming, draggable strike selection, payoff graph, and a strike × date theta-decay table.
- Transaction history with FIFO-matched open/close pairs, realized P&L, and ratio-spread grouping (so a multi-leg combo shows as one row instead of loose legs).
- Reports page: P&L broken down by symbol/week/day, with drill-through into the underlying transactions.
- Price charts with support/resistance overlays.
- Dark mode.
- Copilot: a read-only chat agent (OpenAI) with tool access to your real positions, transactions, and live market data, plus built-in knowledge of common options strategies.
- FastAPI REST layer with auto-generated OpenAPI docs at `/docs`.

---

## Project Structure

```
.
├── api/                  # FastAPI routers (app.py mounts all of them)
│   ├── auth.py           # Login + session token verification
│   ├── market.py         # /positions/... option chain / price history (REST)
│   ├── market_stream.py  # /market/ws/... live chain streaming (WebSocket)
│   ├── position.py       # /positions/... routes
│   ├── transactions.py   # /transactions/... routes
│   └── copilot.py        # /copilot/... routes
├── broker/               # Broker SDKs (broker/schwab, broker/tastytrade)
├── service/              # Business logic (MarketService, PositionService, TransactionService, ...)
├── copilot/              # Copilot agent: system prompt + tool-calling loop (agent.py), tool
│                         # definitions (tools.py), strategy knowledge docs (skills/*.md)
├── frontend/             # React + Vite frontend
│   └── src/
│       ├── pages/        # Positions, Transactions, Reports, StrikeLab, Charts
│       ├── components/   # Navbar, CopilotWidget, DataTable, Spinner
│       ├── utils/        # Small shared helpers (date/symbol formatting, cross-page stores)
│       └── api/          # Fetch wrappers for the FastAPI endpoints
└── main.py               # Schwab OAuth token refresh utility (run this, not the app itself)
```

---

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- Node.js 18+ and npm (for the React frontend)
- A Schwab developer account with an API app (for brokerage data)
- A Tastytrade account with an OAuth application (for live option chains/quotes)
- An OpenAI API key, only if you want the Copilot chat feature

---

## Setting Up on a New Machine

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-username/options-wheel.git
cd options-wheel

uv sync                        # Python deps
cd frontend && npm install && cd ..   # Frontend deps
```

### 2. Get your Schwab API credentials

1. Register an app at Schwab's developer portal and note its **App Key**, **App Secret**, and set a **callback URL** (for local dev this is typically `https://127.0.0.1:8182` or whatever you registered — it doesn't need to be a real running server, just match what you register).
2. You'll use these three values below as `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_APP_CALLBACK_URL`.

### 3. Get your Tastytrade API credentials

1. Register an OAuth application through Tastytrade's developer/API portal and complete the OAuth authorization flow once to obtain a **refresh token** — Tastytrade's own API documentation covers this flow in detail (it's a standard OAuth authorization-code exchange).
2. You'll end up with three values: `TASTY_CLIENT_ID`, `TASTY_CLIENT_SECRET`, and `TASTY_REFRESH_TOKEN`. This app uses the refresh token to mint short-lived access tokens automatically — you shouldn't need to touch this again unless the refresh token itself is revoked.

### 4. Create your `.env` file

Create a `.env` file in the project root (it's loaded automatically on startup — no extra config needed):

```bash
# --- Schwab (required) ---
SCHWAB_APP_KEY=your-schwab-app-key
SCHWAB_APP_SECRET=your-schwab-app-secret
SCHWAB_APP_CALLBACK_URL=https://127.0.0.1:8182

# --- Tastytrade (required for option chains / live quotes) ---
TASTY_CLIENT_ID=your-tastytrade-client-id
TASTY_CLIENT_SECRET=your-tastytrade-client-secret
TASTY_REFRESH_TOKEN=your-tastytrade-refresh-token

# --- App auth (required — this is a single-user app) ---
SECRET_KEY=generate-a-long-random-string
ADMIN_USERNAME=pick-a-username
ADMIN_PASSWORD=pick-a-password

# --- Optional ---
BROKER_PROVIDER=tastytrade     # 'schwab' or 'tastytrade' — which broker serves option chains
                                # (positions/transactions/price history always use Schwab regardless)
OPENAI_API_KEY=sk-...           # only needed for the Copilot chat feature
OPENAI_MODEL=gpt-4o             # defaults to gpt-4o if unset
USE_DB=false                    # true = store the Schwab token in Redis instead of token.json
```

A quick way to generate `SECRET_KEY`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Get your first Schwab token

```bash
uv run python main.py
```

This opens your browser to Schwab's login/consent page. After you approve, Schwab redirects you to your callback URL with a `code` in the query string — copy that **full redirected URL** (even though the page itself won't load, since nothing is listening on it) and paste it into the terminal when prompted. This saves a `token.json` in the project root, which the app reads from on every request. Schwab tokens expire every 7 days — re-run this command when that happens.

### 6. Start the backend

```bash
uv run uvicorn api.app:app --reload
```

- API base URL: `http://localhost:8000`
- Interactive docs (full endpoint list, live): `http://localhost:8000/docs`

### 7. Start the frontend

In a separate terminal, with the backend still running (the frontend proxies API/WebSocket requests to it via Vite):

```bash
cd frontend
npm run dev
```

- URL: `http://localhost:3000`
- Log in with the `ADMIN_USERNAME`/`ADMIN_PASSWORD` you set in `.env`.

### 8. You're in

- **Positions** — balances, stocks, options, futures, futures options.
- **Transactions** — search/filter option and equity transaction history.
- **Reports** — P&L breakdown by symbol/week/day.
- **Analyze** (StrikeLab) — option chain browser and payoff builder.
- **Charts** — price charts with support/resistance.
- **Copilot** (chat icon, bottom-right) — only appears functional if `OPENAI_API_KEY` is set.

---

## API Endpoints

Rather than a hand-maintained list here (which drifts fast), the full live endpoint list with request/response schemas is always available at `http://localhost:8000/docs` once the backend is running. At a glance, routes are grouped under:

| Prefix | Covers |
|---|---|
| `/api/auth` | Login, session verification |
| `/api/market` | Option chains, expirations, price history (REST) |
| `/api/market/ws` | Live option chain streaming (WebSocket) |
| `/api/positions` | Balances, stocks, options, futures, futures options |
| `/api/transactions` | Raw history, matched option transactions, equity transactions |
| `/api/copilot` | The Copilot chat endpoint |

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

Same variables as the local `.env` above, plus `TOKEN_JSON` (Heroku has no local `token.json` file to read from):

| Variable | Required | Description |
|---|---|---|
| `SCHWAB_APP_KEY` | Yes | Schwab API app key |
| `SCHWAB_APP_SECRET` | Yes | Schwab API app secret |
| `SCHWAB_APP_CALLBACK_URL` | Yes | OAuth redirect URI registered in Schwab developer portal |
| `TASTY_CLIENT_ID` | Yes | Tastytrade OAuth client ID |
| `TASTY_CLIENT_SECRET` | Yes | Tastytrade OAuth client secret |
| `TASTY_REFRESH_TOKEN` | Yes | Tastytrade OAuth refresh token |
| `SECRET_KEY` | Yes | Secret key for signing session tokens |
| `ADMIN_USERNAME` | Yes | Login username for the dashboard |
| `ADMIN_PASSWORD` | Yes | Login password for the dashboard |
| `USE_DB` | **Effectively yes, on Heroku** | See warning below — without this, the Schwab token doesn't survive a dyno restart. |
| `REDIS_URL` | If `USE_DB=true` | Redis connection URL (set automatically by the Heroku Redis addon) |
| `TOKEN_JSON` | If `USE_DB=true` | Full Schwab OAuth token as a single-line JSON string — used **only** to re-seed Redis if the stored token there ever expires/is missing. Has no effect at all when `USE_DB` isn't `true` (see warning below). |
| `BROKER_PROVIDER` | No | `schwab` or `tastytrade` — which broker serves option chains. Defaults to `tastytrade` |
| `OPENAI_API_KEY` | For the Copilot feature | OpenAI API key powering the read-only financial copilot chat |
| `OPENAI_MODEL` | No | Model used by the Copilot chat — defaults to `gpt-4o` |

> **Redis is effectively required on Heroku, not optional.** Without `USE_DB=true`, the token is stored in a local `token.json` file (`FileTokenProvider`) — but Heroku's filesystem is ephemeral and gets wiped on every dyno restart, redeploy, or the automatic daily dyno cycle. `TOKEN_JSON` is **only** read by the Redis-backed provider as a re-seed fallback (`broker/schwab/auth/token_provider.py`); there's no code path that seeds `token.json` from it. So setting `TOKEN_JSON` alone, without also setting `USE_DB=true` and provisioning Redis, does nothing — the app will work until the first dyno restart, then every Schwab-dependent endpoint breaks until you re-authenticate. See [Token Storage](#token-storage) below for the Redis setup.

```bash
heroku config:set SCHWAB_APP_KEY=...
heroku config:set SCHWAB_APP_SECRET=...
heroku config:set SCHWAB_APP_CALLBACK_URL=https://your-app.herokuapp.com/callback
heroku config:set TASTY_CLIENT_ID=...
heroku config:set TASTY_CLIENT_SECRET=...
heroku config:set TASTY_REFRESH_TOKEN=...
heroku config:set SECRET_KEY=...
heroku config:set ADMIN_USERNAME=...
heroku config:set ADMIN_PASSWORD=...

# Required for the token to actually persist on Heroku — see warning above
heroku addons:create heroku-redis:mini --app your-app-name
heroku config:set USE_DB=true

# Paste the full token.json contents as a single-line JSON string —
# only takes effect because USE_DB=true was set above
heroku config:set TOKEN_JSON="$(python -c "import json; print(json.dumps(json.load(open('token.json'))))")"
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
| `false` / unset | `token.json` file only — `TOKEN_JSON` env var is not read at all in this mode | Local development (persistent filesystem) |
| `true` | Redis (`REDIS_URL`), re-seeded from `TOKEN_JSON` if the Redis copy ever expires | Production / Heroku (ephemeral filesystem — required there, see the Heroku section above) |

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
