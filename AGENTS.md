# AGENTS.md

Guidance for AI coding agents working in this repository. (Named `AGENTS.md`
rather than `agent.md` — that's the filename convention agentic coding tools
actually look for.)

## What this is

A personal, **single-user** options-wheel trading dashboard: a FastAPI
backend talking to Schwab and Tastytrade, a React (Vite) frontend, and a
read-only AI "copilot" chat agent. No multi-tenancy, no user table — one
hardcoded admin login (`ADMIN_USERNAME`/`ADMIN_PASSWORD`), one brokerage
account. In production, FastAPI serves the built React SPA directly from
`frontend/dist/` (single web process/dyno — see `Procfile`).

## Layout

| Path | What lives there |
|---|---|
| `broker/schwab/` | Schwab REST client — **read-only by design**: quotes, price history, option chains, positions, transactions. No order-placement code exists here at all. |
| `broker/tastytrade/` | Tastytrade REST + DXLink WebSocket client — chains, live quotes/greeks via streaming. Has `place_order`/`cancel_order`/`get_orders` methods that exist in the SDK but are **never called anywhere in the app** — see Guardrails below. |
| `service/` | Business logic: `PositionService`, `TransactionService`, `MarketService`, `option_chain_providers.py` (Schwab vs Tastytrade chain provider, selected by `BROKER_PROVIDER` env var). This is the layer both the REST API and the copilot's tools call into — reuse it rather than reaching into `broker/` directly. |
| `api/` | FastAPI routers: `auth.py`, `market.py`, `market_stream.py` (WebSocket), `position.py`, `transactions.py`, `copilot.py`. Registered in `api/app.py`. |
| `copilot/` | The read-only financial-copilot agent — see its own section below. |
| `frontend/src/pages/` | `Positions`, `Transactions`, `Reports`, `StrikeLab` (routed as `/analyze`), `Charts`, `Login`. |
| `frontend/src/components/` | `Navbar`, `CopilotWidget` (floating chat, mounted globally in `App.jsx`), `DataTable`, `ErrorBoundary`, `Spinner`, `ProtectedRoute`. |
| `frontend/src/context/` | `AuthContext`, `ThemeContext` (dark mode). |
| `frontend/src/styles/tokens.css` | All design tokens (colors, spacing, shadows) as CSS custom properties, including the dark-theme palette under `:root[data-theme="dark"]`. Every other stylesheet should reference tokens, not hardcode colors — a hardcoded color is the single most common way a change quietly breaks dark mode. |

## Guardrails — read before touching trading logic

- **Never wire up `TastytradeClient.place_order` / `.cancel_order` /
  `.get_orders`** to any service, API route, or the copilot's tools. They're
  intentionally unused. Tastytrade also defaults to the **production**
  endpoint, not sandbox — a real key there acts on a real account.
- **The copilot (`copilot/`) is strictly read-only** — this is a documented
  hard constraint in `copilot/agent.py`'s system prompt, not just a Tastytrade
  fact. Don't add a tool that can place, modify, or cancel anything.
- **Futures symbols use the `"/ES"`/`"/NQ"` convention (leading slash)**
  consistently across `MarketService`, `TastytradeClient`, and the copilot's
  tools. `TransactionService._populate_options`/`_populate_equity_futures`
  strip a leading `/` before matching against Schwab's internally-normalized
  bare-root symbols — if you add a new ticker-filtering code path, make sure
  it accepts both forms, or it'll silently return zero results for a
  perfectly valid futures query (this exact bug shipped once already).
- **`BROKER_PROVIDER`** env var (`"schwab"` or `"tastytrade"`, default
  `tastytrade`) selects which broker serves *option chains*. Positions,
  transactions, and price history always go through Schwab regardless —
  don't assume `BROKER_PROVIDER` gates those too.

## Auth

Custom HMAC-SHA256 signed tokens (`api/auth.py`), **not** JWT — 8-hour TTL,
single hardcoded admin credential pair from env vars, secret from
`SECRET_KEY`. REST routes use `Depends(require_auth)` (Bearer header).
WebSocket routes (`market_stream.py`) can't carry an `Authorization` header,
so they pass the token as a `?token=` query param and call `verify_token()`
manually inside the handler — follow that same pattern for any new WS route.

## The copilot agent (`copilot/`)

- `tools.py` — plain Python functions + hand-written OpenAI function-calling
  JSON schemas (`TOOL_SCHEMAS`) wrapping existing `service/` methods. The
  core `openai` SDK has no decorator-based auto-schema helper, so schemas
  must be kept in sync with each function's signature by hand.
- `agent.py` — builds the system prompt (identity, hard read-only + hard
  net-credit-only constraints, concatenated skill docs) and drives OpenAI's
  tool-calling loop manually (`while` over `chat.completions.create`, since
  there's no built-in agentic-loop helper in the plain SDK). Model is
  `OPENAI_MODEL` env var, default `gpt-4o` — check what's actually current
  before assuming that default is still right; it's been bumped before.
- `skills/*.md` — options-strategy reference docs, loaded in full into the
  system prompt (no RAG — the set is small enough that retrieval would be
  pure overhead for a single-user app). Adding a new strategy = adding a new
  `.md` file here; nothing else needs to change to pick it up.
- `TransactionService.group_ratio_spreads()` merges matched trade legs that
  form a ratio spread into one record before the copilot (and, via a
  `group_ratio_spreads=true` query param, the Transactions page) sees them.
  It carries an internal total-P&L consistency check that falls back to the
  ungrouped result if grouping would ever change the sum — if you touch that
  method, keep that guard.

## Frontend conventions

- Plain CSS with design tokens (`frontend/src/styles/tokens.css`) — no
  Tailwind, no CSS-in-JS. `.tab-row`/`.tab-item` for in-page view switchers
  (Chain/Table/Graph-style), deliberately styled differently from `.btn` so
  a tab strip doesn't read as a row of action buttons.
- Dark mode: `ThemeContext` sets `data-theme` on `<html>`, persisted to
  `localStorage`, with an inline script in `index.html` to avoid a
  flash-of-wrong-theme on load. Any new color must go through a token —
  check both the light and dark blocks in `tokens.css` before shipping.
- Several pages keep a plain module-level object (e.g. `strikeLabCache` in
  `StrikeLab.jsx`, `symbolStore` in `utils/symbolStore.js`) to survive
  navigating away and back within a session, without a real state library.
  `symbolStore` is intentionally shared between StrikeLab and Charts so
  picking a symbol on one carries over to the other.
- `frontend/src/api/client.js` is a flat set of exported functions around a
  shared `request(path, options)` helper (Bearer auth, redirects to
  `/login` on 401). Follow that pattern for new endpoints rather than
  introducing a second HTTP client.

## Dev workflow

```bash
# Backend (from repo root)
uv run uvicorn api.app:app --reload

# Frontend (separate terminal)
cd frontend && npm run dev
```

- Python deps: `uv add <pkg>` / `uv remove <pkg>` (keeps `pyproject.toml`
  and `uv.lock` in sync — don't hand-edit the lock file).
- JS deps: `npm install <pkg>` from `frontend/`.
- No automated test suite exists (`tests/` is empty) — verify changes by
  running the dev servers and exercising the feature directly, or with
  targeted one-off scripts for backend logic.
- Logs: `logs/api.log` (rotating), useful for debugging live broker/DXLink
  behavior — `--log-level debug` on uvicorn surfaces the raw WebSocket
  frames, which has been the fastest way to diagnose several past bugs here.

## Key env vars

See the README's env var table for the full deployment list. The ones most
relevant to day-to-day agent work: `BROKER_PROVIDER`, `SCHWAB_APP_KEY` /
`SCHWAB_APP_SECRET` / `SCHWAB_APP_CALLBACK_URL`, `TASTY_CLIENT_ID` /
`TASTY_CLIENT_SECRET` / `TASTY_REFRESH_TOKEN`, `OPENAI_API_KEY` /
`OPENAI_MODEL`, `SECRET_KEY`, `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
