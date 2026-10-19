# Options Wheel

Options Wheel is a Python-based trading dashboard for running options strategies against real brokerage accounts. It's a small multi-user app (you as admin, plus friends you create accounts for): FastAPI backend, React + Vite frontend, backed by the Schwab API (positions, balances, transaction history — always read-only, no order placement exists anywhere in this app) and Tastytrade (live option chains, streaming quotes via DXLink). It also ships a read-only AI "Copilot" chat for asking questions about your own account and market data.

For a deeper architectural tour (service layer, broker clients, copilot subsystem, frontend conventions), see [`AGENTS.md`](./AGENTS.md). This README is the practical "get it running" guide.

---

## Features

- Account positions, balances, and stock/ETF holdings, plus derived futures and futures-option positions (Schwab's positions API doesn't return either, so those are reconstructed from transaction history).
- Options chain browser and payoff/P&L analyzer ("Analyze" / StrikeLab) — live chain streaming, draggable strike selection, payoff graph, and a strike × date theta-decay table.
- Transaction history with FIFO-matched open/close pairs, realized P&L, and ratio-spread grouping (so a multi-leg combo shows as one row instead of loose legs).
- Reports page: P&L broken down by symbol/week/day, with drill-through into the underlying transactions.
- Price charts with support/resistance overlays.
- Options Screener: scan a list of tickers for the short puts/calls, 1×2 ratio puts, or jade lizards that pay the most to sell (ranked by annualized ROI), or the long puts/calls with the most leverage to buy — filtered by moneyness, DTE, and (optionally) delta — then send the picks straight to Analyze.
- Multiple users: you (admin) create accounts for friends in Settings → Users. Each user connects their own Schwab account; live market data is shared; the Copilot is admin-only.
- Dark mode.
- Copilot: a read-only chat agent (OpenAI) with tool access to your real positions, transactions, and live market data, plus built-in knowledge of common options strategies.
- FastAPI REST layer with auto-generated OpenAPI docs at `/docs`.

---

## Project Structure

```
.
├── api/                  # FastAPI routers (app.py mounts all of them)
│   ├── auth.py           # Login + session token verification
│   ├── market.py         # /market/... option chain, screener, price history (REST)
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
│       ├── pages/        # Landing, Positions, Transactions, Reports, StrikeLab, Charts, Screener, Settings
│       ├── components/   # Navbar, CopilotWidget, DataTable, HelpTip, Spinner
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

# --- App auth (required) — ADMIN_* create the first admin account on an empty user database ---
SECRET_KEY=generate-a-long-random-string
ADMIN_USERNAME=pick-a-username
ADMIN_PASSWORD=pick-a-password

# --- Optional ---
CHAIN_PROVIDER=tastytrade     # 'schwab' or 'tastytrade' — which broker serves option chains
                                # (positions/transactions always use Schwab; Charts always uses Tastytrade)
OPENAI_API_KEY=sk-...           # only needed for the Copilot chat feature
OPENAI_MODEL=gpt-4o             # defaults to gpt-4o if unset
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

- URL: `https://127.0.0.1:3000` opens the public landing page; **Log in** opens the login form over it. The dev server uses HTTPS with a self-signed certificate (click through the browser's one-time warning). Schwab only accepts HTTPS callback URLs, so this is what lets **Settings → Reconnect Schwab** work locally: register `https://127.0.0.1:3000/api/auth/schwab/callback` in Schwab's developer portal and set it as `SCHWAB_APP_CALLBACK_URL` in `.env`. Use `127.0.0.1`, not `localhost` — the app login is stored per address, and that's where Schwab sends you back.
- Log in with the `ADMIN_USERNAME`/`ADMIN_PASSWORD` you set in `.env`.

### 8. You're in

- **Positions** — balances, stocks, options, futures, futures options.
- **Transactions** — search/filter option and equity transaction history.
- **Reports** — P&L breakdown by symbol/week/day.
- **Analyze** (StrikeLab) — option chain browser and payoff builder.
- **Charts** — price charts with support/resistance.
- **Screener** — top short puts/calls, ratio puts, or jade lizards to sell, or long puts/calls to buy, across a list of tickers (see [Options Screener](#options-screener) below).
- **Settings** (bottom of the menu) — your account (change password), Schwab connection, light/dark theme, and — for admins — **Users** (create accounts, reset passwords, disable/delete).
- **Copilot** (chat icon, bottom-right) — only appears functional if `OPENAI_API_KEY` is set.

---

## Options Screener

The **Screener** page ranks single puts or calls — or two multi-leg credit strategies — across a list of tickers by how much they return to *sell*, or long puts/calls by how much leverage they give to *buy*.

**Search criteria** (all on one row):

| Field | Notes |
|---|---|
| Tickers | Comma- or space-separated, up to 25. Futures roots (`/ES`) work too. |
| Option Type | One per scan: **Short Puts**, **Short Calls**, **Long Puts**, **Long Calls**, **Ratio Put (1×2)**, or **Jade Lizard** (see below). Default Short Puts. |
| Moneyness (% OTM) | Required min–max. Measured from spot toward worthless: below spot for puts, above for calls. A negative min reaches into ITM strikes. Default 0–3. |
| DTE | Min–max days to expiration, 0–365. Default 0–7. |
| Delta (optional) | Min–max **absolute** delta, so 0.15–0.30 matches a −0.20 put and a 0.20 call. Leave either side blank for no limit. Narrows the moneyness range rather than replacing it. For strategies it applies to the legs you sell. |

**Strategies** (built within each expiration; every leg must sit inside the moneyness range):

- **Ratio Put (1×2)** — buy 1 put, sell 2 puts at a strictly lower strike. Only combinations that open for a net credit (`2 × short bid − long ask > 0`), matching the copilot's rules in `copilot/skills/put_ratio_spread.md`.
- **Jade Lizard** — sell 1 put, plus a call spread above it (sell 1 call, buy 1 call up to 5 strikes higher), with total credit ≥ the call spread's width, so there's no upside risk.

**How results are ranked:**

- **Premium** is the **bid** — what a sell order can actually fill at — not the mid. Contracts with no bid are skipped.
- **ROI** = (bid − intrinsic) ÷ capital, i.e. the return if the underlying is unchanged at expiration. Capital is the strike for a cash-secured put and spot for a covered call. Intrinsic is subtracted so deep-ITM contracts don't top the list with premium that's handed straight back on assignment.
- **Strategies** price sold legs at the bid and bought legs at the ask. ROI is the P&L if the underlying is unchanged at expiration ÷ capital, where capital is the **max loss if the stock went to zero** (both strategies carry naked-put-style downside). The table shows credit, max profit, breakeven(s), and capital per share.
- **Ann. ROI** = ROI × 365 ÷ DTE — the default sort, so a weekly and a 45-DTE contract are comparable. The top 200 matches are returned.
- **Long Puts / Long Calls** are bought at the **ask** (also the max loss) and ranked by **leverage (λ)** = |delta| × spot ÷ ask — roughly the option's % change for a 1% move in the stock — instead of ROI, whose "price unchanged" premise doesn't fit a long option. The table also shows breakeven and **BE Move %** (how far the stock must move in your favor by expiration to break even). λ naturally favors cheap far-OTM contracts; use the delta range to focus on more realistic strikes.

**Analyze Selected:** tick one or more rows and click **Analyze Selected** to open them in Analyze (StrikeLab) — a short contract as a short 1-lot leg priced at the bid, a long contract as a long 1-lot leg at the ask, a strategy row as all of its legs at the prices above — with the Range ± slider widened to fit every strike and breakeven. Selected rows must share one ticker and expiration — same rule as on Positions.

**Limits worth knowing:**

- Each ticker is capped at 600 contracts per scan so one live-quote snapshot fills reliably. Over the cap, the strikes nearest the money are kept and the page shows a warning — narrow the DTE or moneyness range to see everything.
- A ticker that fails (bad symbol, no listed options) is reported as a per-ticker warning; the rest of the scan still returns.
- Option chains come from whichever broker `CHAIN_PROVIDER` selects. A scan of several tickers typically takes ~10–15 s.
- For futures options, ROI is still premium ÷ strike, which doesn't reflect the margin actually tied up.

---

## API Endpoints

Rather than a hand-maintained list here (which drifts fast), the full live endpoint list with request/response schemas is always available at `http://localhost:8000/docs` once the backend is running. At a glance, routes are grouped under:

| Prefix | Covers |
|---|---|
| `/api/auth` | Login, session verification |
| `/api/market` | Option chains, expirations, options screener, price history (REST) |
| `/api/market/ws` | Live option chain streaming (WebSocket) |
| `/api/positions` | Balances, stocks, options, futures, futures options |
| `/api/transactions` | Raw history, matched option transactions, equity transactions |
| `/api/copilot` | The Copilot chat endpoint |

---

## Deploying to Fly.io

The app runs as **one small Fly machine** (shared-cpu-1x, 512MB — about $3.69/month if always on, less with the auto-stop below) from the repo's `Dockerfile` and `fly.toml`. The Docker build compiles the React app and FastAPI serves it alongside the API, same single-process layout as local. Schwab tokens and the user database live on a **1GB Fly volume** mounted at `/data`, so they survive restarts and redeploys.

### One-time setup

```bash
# 1. Install the CLI and log in
brew install flyctl
fly auth login

# 2. Create the app. App names are global on Fly — pick your own. This keeps
#    the repo's fly.toml and just writes your app name into it.
fly launch --no-deploy --copy-config --name your-app-name

# 3. Create the volume for token.json (same region as fly.toml's primary_region)
fly volumes create data --size 1 --region iad

# 4. Set secrets from your local .env (see the note below)
{
  grep -E '^(SCHWAB_APP_KEY|SCHWAB_APP_SECRET|TASTY_CLIENT_ID|TASTY_CLIENT_SECRET|TASTY_REFRESH_TOKEN|OPENAI_API_KEY|OPENAI_MODEL|ACCOUNT_BROKER_PROVIDER|ADMIN_USERNAME|ADMIN_PASSWORD|SECRET_KEY)=' .env \
    | sed -E "s/^([A-Z_]+)=[\"'](.*)[\"']$/\1=\2/"
  echo "SCHWAB_APP_CALLBACK_URL=https://your-app-name.fly.dev/api/auth/schwab/callback"
} | fly secrets import
fly secrets list    # should list all 12 names

# 5. Deploy as a single machine (a volume attaches to exactly one machine)
fly deploy --ha=false
```

About step 4:
- It copies the needed keys from `.env` without printing them, strips surrounding quotes (`fly secrets import` would otherwise keep them as part of the value), and swaps in the Fly callback URL.
- It copies only the keys the app needs as secrets; `CHAIN_PROVIDER` is left out because it's already in `fly.toml`.
- Prefer this over a long multi-line `fly secrets set … \` command: one broken line continuation there silently sets only the first secret, which leaves login failing with 401.
- To use a different `SECRET_KEY` in production than locally, drop it from the `grep` list and add `echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"`.

Non-secret settings (`PORT`, `TOKEN_FILE=/data/token.json`, `LOG_TO_STDOUT`, `CHAIN_PROVIDER`) are in `fly.toml`'s `[env]` block — edit them there.

### Connect Schwab (and reconnect every 7 days)

Schwab's refresh token lasts **7 days** and can only be renewed by logging in again — the app renews the short-lived access token on its own, but not that. The app runs this login itself:

1. **One-time:** in Schwab's developer portal, add `https://your-app-name.fly.dev/api/auth/schwab/callback` to your app's callback URLs (keep your local one too, if Schwab lets you list several), and make sure `SCHWAB_APP_CALLBACK_URL` on Fly is set to it (step 4 above).
2. In the app, open **Settings → Schwab Connection** and click **Connect Schwab** (later: **Reconnect Schwab**). You're sent to Schwab to log in and approve, then back to Settings, which shows when the new login expires — it turns amber in the last day. The token is saved straight to the volume.

Do step 2 whenever it's due (or when pages show "Broker authentication failed") — from any device, no CLI needed.

**Fallback** (e.g. before the callback URL is registered): generate the token locally with `uv run python main.py` and copy it onto the volume:

```bash
fly machine start                              # in case it's auto-stopped
fly ssh console -C "rm -f /data/token.json"    # sftp won't overwrite an existing file
fly ssh sftp shell
» put token.json /data/token.json
```

### Pushing new code

From the repo root (the app name comes from `fly.toml`, so no `-a` needed):

```bash
fly deploy
```

That's the whole deploy. What it does:

1. Uploads the working directory to Fly's remote builder — **uncommitted changes included**, so commit first if you want the deployed version to match git. Files in `.dockerignore` (`.env`, `token.json`, `config.py`, `node_modules`, `.venv`, …) are never uploaded.
2. Builds the `Dockerfile`: `npm ci && npm run build` for the frontend, `uv sync --frozen` for Python (from `uv.lock` — run `uv lock` locally first if you changed `pyproject.toml`).
3. Replaces the machine with the new image. The `/data` volume (Schwab token) and secrets carry over — no need to reconnect Schwab.

Then check it:

```bash
fly status          # machine "started", health check "passing"
fly logs            # watch startup; Ctrl+C to stop
```

and open `https://your-app-name.fly.dev`. A hard refresh (Cmd+Shift+R) makes sure the browser loads the new frontend bundle.

**What needs a deploy vs. not:**

| Change | How to apply |
|---|---|
| Code (Python or React) | `fly deploy` |
| `fly.toml` (`[env]`, VM size, auto-stop, …) | `fly deploy` |
| A secret | `fly secrets set NAME=value` — restarts the machine on its own, no deploy |
| Python dependencies | `uv add <pkg>` locally (updates `uv.lock`), then `fly deploy` |
| JS dependencies | `npm install <pkg>` in `frontend/` (updates `package-lock.json`), then `fly deploy` |

**Roll back** a bad deploy to the previous image:

```bash
fly releases --image                                  # list releases with their image tags
fly deploy --image registry.fly.io/your-app-name:<previous-image-tag>
```

### Day to day

- **Open:** `https://your-app-name.fly.dev` (log in with `ADMIN_USERNAME`/`ADMIN_PASSWORD`).
- **Weekly:** Settings → **Reconnect Schwab** when it turns amber or expires (each user does their own).
- **Add a friend:** Settings → **Users** → enter a username, click **Generate** for a password, **Create user**, and send them both. They log in at your app URL, change their password in Settings, and click **Connect Schwab**. Their Schwab token is stored separately (`/data/schwab_tokens/user_<id>.json`) — they never see your data, and you never see theirs in the app.
- **Accounts live in** `/data/nutrade.db` (SQLite on the volume), so they survive redeploys. `ADMIN_USERNAME`/`ADMIN_PASSWORD` only create the very first admin when that database is empty — after that, change your password in Settings, not in secrets.
- **Logs:** `fly logs` (the app mirrors its log to stdout on Fly via `LOG_TO_STDOUT`).
- **Auto-stop:** the machine stops when nothing is connected and starts on the next request, so you mostly pay for hours actually used — the first page load after idle takes a few seconds. An open Analyze chain stream counts as a connection and keeps it running. Set `min_machines_running = 1` in `fly.toml` (then `fly deploy`) to keep it always on instead.
- **Sessions:** you're signed out after **15 minutes of inactivity** (clicks, typing, scrolling); while you're using the app it renews itself in the background. Background refreshes and the Analyze live stream don't count as activity, so an idle tab signs out and the machine can auto-stop.
- **Shell into the machine:** `fly ssh console` (start it first with `fly machine start` if it's auto-stopped).

### Troubleshooting

**Login fails (wrong username/password, `401` in `fly logs`)**
- On a brand-new deploy: the first admin comes from `ADMIN_USERNAME`/`ADMIN_PASSWORD` — check `fly secrets list` and re-run step 4 if they're missing.
- After that, passwords live in the database, so changing those secrets does nothing. A friend who forgot theirs: Settings → Users → **Reset password**. If *you* are locked out:
  ```bash
  fly ssh console -C "python -m api.users reset-password <your-username>"
  ```
  (locally: `uv run python -m api.users reset-password <your-username>`). It prompts for the new password and re-enables the account.
- Disabled accounts can't log in (same "invalid" message, by design).

**Checking a secret's value**
`fly secrets list` shows names and digests only, never values. To read one: `fly ssh console -C "printenv ADMIN_USERNAME"`. To confirm it matches `.env` without printing it, compare fingerprints:
```bash
fly ssh console -C "sh -c 'printf %s \"\$SECRET_KEY\" | sha256sum'"
grep '^SECRET_KEY=' .env | cut -d= -f2- | tr -d "\"'\n" | shasum -a 256
```

**Pages say "Broker authentication failed — … Reconnect Schwab in Settings"**
Schwab isn't connected yet for *this user*, or their 7-day login expired — each user connects their own. Settings → **Connect / Reconnect Schwab**. Charts, Screener and Analyze don't depend on Schwab (they use Tastytrade), so they keep working meanwhile.

**Schwab shows "We are unable to complete your request. Please contact customer support…"**
Schwab rejected the `redirect_uri` — it must match a callback URL registered in Schwab's developer portal **exactly** (`https`, host, port, path, no trailing slash). Check:
- the portal lists `https://your-app-name.fly.dev/api/auth/schwab/callback` (Schwab can take a while to apply portal changes);
- `fly ssh console -C "printenv SCHWAB_APP_CALLBACK_URL"` prints that same URL.

Locally the same error usually means a **stale backend**: `.env` changes are only read at startup — `--reload` and the VS Code debugger keep the old value — so fully stop and restart the backend.

**After Schwab login you land on `/login` instead of Settings**
The Schwab connection itself still succeeded (check `fly logs` for `Schwab reconnected via the in-app flow`); only the app login was lost on the way back. Log in again — Settings shows the new expiry. (The app hands its login across the redirect; if this keeps happening, the app login may have timed out — sessions end after 15 minutes without activity, and time on Schwab's page counts.)

**Deploy fails: volume / mount error**
The `data` volume doesn't exist in the machine's region: `fly volumes list`, then `fly volumes create data --size 1 --region iad`. Deploy with `--ha=false` the first time — a volume attaches to only one machine.

**Health check failing / site not loading after a deploy**
`fly logs` shows the startup error (a Python traceback, or the build failing). Common causes: `uv.lock` out of date with `pyproject.toml` (run `uv lock`, redeploy), or a new required env var that isn't set as a secret. Roll back with `fly deploy --image …` (above) while you fix it. A few failed checks right after a deploy or a cold start are normal while the machine boots.

**First load is slow**
The machine was auto-stopped and is booting (a few seconds). Expected with `min_machines_running = 0`.

**Charts show "No price history" for 5Y / MAX**
These use monthly bars from Tastytrade's DXLink feed, which sometimes returns nothing for a *repeated* long-history request. Successful results are cached in memory for 12 hours, so it's usually a first-request-after-restart issue — try again shortly.

**Is Schwab rotating the refresh token?**
Each access-token refresh logs either `refresh token unchanged` or `Schwab issued a NEW refresh token (rotated)`: `fly logs | grep "refresh token"`.

**Making sure `.env` never ships**
`.dockerignore` excludes `.env`, `.env.*`, `token.json` and `config.py` from the upload, and the app gets credentials only from `fly secrets`. Verify on the live machine:
```bash
fly ssh console -C "ls -la /app/.env /app/token.json"    # want: No such file or directory (both)
```
Keep those lines in `.dockerignore`, and add any new secret file you create.

**Local development**
- Open `https://127.0.0.1:3000` (not `localhost`) and accept the self-signed certificate warning once.
- Changed `.env`? Restart the backend fully (see the Schwab error above).
- Odd frontend behavior after dependency changes: stop Vite, `rm -rf frontend/node_modules/.vite`, start it again.

---

## Token Storage

Each user's Schwab OAuth token is stored as a JSON file:

| User | File |
|---|---|
| The original admin | `TOKEN_FILE` if set, else `./token.json` in the project root (Fly sets `TOKEN_FILE=/data/token.json`) |
| Everyone else | `schwab_tokens/user_<id>.json` in the same folder |

Files are written atomically and readable only by the app's own user (mode 0600). No extra configuration is needed locally; on Fly they're on the `/data` volume.

The access token is refreshed automatically (shortly before it expires, or on a `401`) and written back to the file. The refresh token itself expires after 7 days — reconnect from **Settings → Schwab Connection** (or, for the admin locally, re-run `main.py`).
