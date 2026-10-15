# AGENTS.md

Guidance for AI coding agents working in this repository. (Named `AGENTS.md`
rather than `agent.md` — that's the filename convention agentic coding tools
actually look for.)

## What this is

A small **multi-user** (admin + friends) options trading dashboard: a
FastAPI backend talking to Schwab and Tastytrade, a React (Vite) frontend,
and a read-only AI "copilot" chat agent. Accounts are admin-managed (no
self-service sign-up) and live in SQLite (`api/users.py`). **Each user has
their own Schwab connection** (positions/transactions are per-user);
**market data is shared** through the one Tastytrade account in env
(`TASTY_*`); the **Copilot is admin-only**. In production, FastAPI serves the built React SPA directly from
`frontend/dist/` (single web process — see `Dockerfile` / `fly.toml`, deployed to Fly.io).

## Layout

| Path | What lives there |
|---|---|
| `broker/schwab/` | Schwab REST client — **read-only by design**: quotes, price history (no longer used by Charts), option chains, positions, transactions. No order-placement code exists here at all. |
| `broker/tastytrade/` | Tastytrade REST + DXLink WebSocket client — chains, live quotes/greeks via streaming. Has `place_order`/`cancel_order`/`get_orders` methods that exist in the SDK but are **never called anywhere in the app** — see Guardrails below. |
| `service/` | Business logic: `PositionService`, `TransactionService`, `MarketService`, `option_chain_providers.py` (Schwab vs Tastytrade chain provider, selected by `CHAIN_PROVIDER` env var). `strategy_builder.py` is the Analyze page's Strategy Builder: data-driven templates (adding a strategy = one `TEMPLATES` entry) solved against one expiration's chain at mid prices; it and `screener_strategies.py` share the payoff math in `strategy_math.py`. This is the layer both the REST API and the copilot's tools call into — reuse it rather than reaching into `broker/` directly. |
| `api/` | FastAPI routers: `auth.py`, `market.py`, `market_stream.py` (WebSocket), `position.py`, `transactions.py`, `copilot.py`. Registered in `api/app.py`. |
| `copilot/` | The read-only financial-copilot agent — see its own section below. |
| `frontend/src/pages/` | `Landing` (public page at `/`; Log in / Register open as overlays on it, and `/login` — where `ProtectedRoute` sends logged-out visitors, remembering the page they wanted — is the same page with the login overlay open. Its screenshots in `frontend/public/landing/` are real captures, and since the page is public they must never show real account data or the real user: market-data pages (Screener, Analyze/Strategy Builder, Charts) are shot on live market data, and the hero's Reports shot uses **sample P&L** via mocked API responses, with the sidebar user mocked as "Demo Trader" — never capture Positions/Transactions/Reports on real data. Register only explains that the admin creates accounts — there's no self-service sign-up), `Positions`, `Transactions`, `Reports`, `StrikeLab` (routed as `/analyze`), `Charts`, `Screener` (top puts/calls to sell across tickers, ranked by annualized ROI — backed by `MarketService.screen_options` + each chain provider's `get_screener_contracts`; multi-leg Ratio Put / Jade Lizard combinations are built in `service/screener_strategies.py`), `Settings` (account/change password, Schwab connection, light/dark theme — not in the navbar — and the admin-only Users card, `components/AccountSettings.jsx`), `Login`. |
| `frontend/src/components/` | `Navbar`, `CopilotWidget` (floating chat, mounted globally in `App.jsx`), `DataTable`, `ErrorBoundary`, `RequireSchwab` (wraps the Portfolio routes in `App.jsx`: checks the user's Schwab connection first and shows a connect/reconnect notice instead of the page when it's missing or expired — wrap any new page that reads Schwab account data the same way), `LoginCard` (the login form, used by the landing page's overlay), `HelpTip` ("?" button + pop-up beside a form label — use it for field help text instead of a paragraph under the form), `StrategyBuilderOverlay` (the Analyze page's "Build Strategy" overlay — its form is generated from `GET /api/market/strategies`; applied legs go through StrikeLab's `applyLegs`, which the copilot Apply also uses), `Spinner`, `ProtectedRoute`. |
| `frontend/src/context/` | `AuthContext`, `ThemeContext` (dark mode). |
| `frontend/src/utils/` | Small shared helpers, not page-specific: `optionSymbol.js` (the one canonical "TICKER MM/DD/YYYY STRIKE.00 P/C" formatter — every page showing an option contract should call this, not re-derive its own), `dateFormat.js` (MM/DD/YYYY), `contractMultiplier.js` (equity=100 vs futures-root multipliers + `isFuturesRoot`), `copilotContext.js` (see Copilot section below), `symbolStore.js` (see below). |
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
- **`CHAIN_PROVIDER`** env var (`"schwab"` or `"tastytrade"`, default
  `tastytrade`) selects which broker serves *option chains*. Positions and
  transactions always go through Schwab, and Charts' price history always
  through Tastytrade (DXLink `Candle` events via
  `TastytradeClient.get_candles`) — don't assume `CHAIN_PROVIDER` gates
  either. DXLink's history depth varies by bar size (monthly: decades;
  daily: ~2 years; weekly: only months) and repeat long-history requests
  can come back empty, which is why 5Y/MAX use monthly bars and
  `MarketService` caches results per (symbol, range).

## Auth

Custom HMAC-SHA256 signed tokens (`api/auth.py`), **not** JWT — **15-minute
TTL, renewed while the user is active**: `AuthContext` tracks real input
(not polling or the Analyze stream) and calls `POST /api/auth/refresh` once
a token is 5 minutes old; after 15 idle minutes it signs out (which also
closes the Analyze WebSocket, so an idle tab lets the Fly machine
auto-stop). Don't make background requests count as activity.
secret from `SECRET_KEY`, payload `u<user id>:<issued ms>`. A token is only
valid while its user exists, is enabled, and hasn't changed password since
it was issued (so disable/reset signs them out). Users are in SQLite
(`api/users.py`, `DB_PATH`, default next to `TOKEN_FILE` — on Fly the /data
volume); passwords are scrypt-hashed; the first admin is bootstrapped from
`ADMIN_USERNAME`/`ADMIN_PASSWORD` only when the table is empty, after which
the DB is authoritative (recovery: `uv run python -m api.users
reset-password <name>`). Admin user management is `api/admin.py`
(`require_admin`); the Copilot router is also `require_admin`.

**Per-user Schwab tokens — the guardrail that matters most.**
`require_auth` (deliberately `async`, so its ContextVar reaches the route
handler) calls `set_token_owner(user.id)`, and `create_token_provider()` —
which every Schwab client uses — picks that user's store: user 1 (the
bootstrap admin) keeps the legacy `TOKEN_FILE`; everyone else gets
`schwab_tokens/user_<id>.json` next to it. The web app calls
`require_token_owner()` at startup, so a Schwab call with **no** user
context raises instead of silently falling back to the admin's token
(another person's account). ContextVars don't flow into threads a service
starts itself: any ThreadPoolExecutor that could reach Schwab must submit
work via `contextvars.copy_context().run` (one copy per task), as
`MarketService.screen_options` does. Never cache account data at module
level — services are built per request, and that's what keeps users apart.

REST routes use `Depends(require_auth)` (Bearer header).
The Schwab OAuth reconnect (`/api/auth/schwab/start|callback|status`, used
by Settings) is the one exception to Bearer auth on the callback: Schwab's
browser redirect can't carry the header, so `start` (Bearer-protected)
issues a signed, 10-minute `state` carrying the user id — HMAC'd with a key *derived* from
`SECRET_KEY`, deliberately not the login-token key, so a state value (which
lands in browser history) can never pass as a login token — and `callback`
rejects anything without a valid one. Token saves go through
`create_token_provider()`, which also records `refresh_token_issued_at` so
Settings can show the 7-day expiry.
Schwab tokens are served from a **process-wide in-memory cache**
(`token_provider.py`, shared across every client's provider instance):
token.json is re-read only when its mtime changes (so an external
`main.py`/sftp replacement is picked up), saves are atomic (temp file +
`os.replace`, mode 0600), and `BaseClient` refreshes the access token
~60s *before* expiry, with a re-check under `_refresh_lock` so concurrent
threads trigger one refresh. Read tokens through the provider, never by
opening token.json directly. Each refresh logs whether Schwab rotated the
refresh token — pending confirmation of that behavior before persisting
the refresh token only on reconnect.
WebSocket routes (`market_stream.py`) can't carry an `Authorization` header,
so they pass the token as a `?token=` query param and call `verify_token()`
manually inside the handler — follow that same pattern for any new WS route.

## The copilot agent (`copilot/`)

- `tools.py` — plain Python functions + hand-written OpenAI function-calling
  JSON schemas (`TOOL_SCHEMAS`) wrapping existing `service/` methods. The
  core `openai` SDK has no decorator-based auto-schema helper, so schemas
  must be kept in sync with each function's signature by hand.
  `build_strategy` wraps the Analyze page's Strategy Builder solver
  (`MarketService.build_strategy`) and is limited to credit templates
  (`COPILOT_STRATEGY_DIRECTIONS`), matching the net-credit rule in
  `agent.py`. Its schema's strategy/leg-key list is generated from
  `strategy_builder.TEMPLATES`, so it can't drift.
- `agent.py` — builds the system prompt (identity, hard read-only + hard
  net-credit-only constraints, concatenated skill docs) and drives OpenAI's
  tool-calling loop manually (`while` over `chat.completions.create`, since
  there's no built-in agentic-loop helper in the plain SDK). Model is
  `OPENAI_MODEL` env var, default `gpt-4o` — check what's actually current
  before assuming that default is still right; it's been bumped before.
- `skills/*.md` — options-strategy reference docs, loaded in full into the
  system prompt (no RAG — the set is small enough that retrieval would be
  pure overhead for an app this size). Adding a new strategy = adding a new
  `.md` file here; nothing else needs to change to pick it up.
- `TransactionService.group_ratio_spreads()` (closed/historical trades) and
  `.group_open_ratio_spreads()` (currently-open legs, used by the Positions
  page's futures-option tables) both merge matched trade legs that form a
  ratio spread into one record — same qualification rules (exactly two
  strikes, one side net long/short, whole-number ratio ≥ 2), same internal
  consistency guard (total P&L for closed, total quantity for open) that
  falls back to the ungrouped result rather than risk silently misstating a
  number. If you touch either method, keep that guard.
- The copilot can see **what the user is currently looking at**, not just
  brokerage data: a page sets `frontend/src/utils/copilotContext.js`
  (`setCopilotContext(page, data)`) whenever its relevant state changes —
  StrikeLab does this with the in-progress position (legs, spot, IV, net
  credit, max profit/loss). `CopilotWidget` reads it fresh at send time and
  passes it as `context: {page, data}` in the `/copilot/chat` request;
  `agent.py`'s `chat(messages, page_context=...)` folds it into that turn's
  system prompt as a labeled, explicitly-a-snapshot block. It's a plain
  module-level store (mounted-once `CopilotWidget` has no prop path into a
  routed page's state), same pattern as `symbolStore.js` (Layout table
  above) — add a new page's context the same way rather than inventing a
  second mechanism.

## Frontend conventions

- Plain CSS with design tokens (`frontend/src/styles/tokens.css`) — no
  Tailwind, no CSS-in-JS. `.tab-row`/`.tab-item` for in-page view switchers
  (Chain/Table/Graph-style), deliberately styled differently from `.btn` so
  a tab strip doesn't read as a row of action buttons.
- Dark mode: chosen on the Settings page (`/settings`). `ThemeContext` sets `data-theme` on `<html>`, persisted to
  `localStorage`, with an inline script in `index.html` to avoid a
  flash-of-wrong-theme on load. Any new color must go through a token —
  check both the light and dark blocks in `tokens.css` before shipping.
- **Don't cache brokerage account data in memory.** Positions, Transactions
  and Reports load fresh on every visit. Any other module-level page cache
  must be created with `createSessionCache()` (or register a reset with
  `registerSessionReset()`) from `utils/sessionCaches.js`; `AuthContext`
  clears them all on login/logout. Module state outlives a sign-out on the
  same tab, so a plain module object here once showed the previous user's
  Schwab positions to the next user who signed in.
- Several pages keep a plain module-level object (e.g. `strikeLabCache` in
  `StrikeLab.jsx`, `symbolStore` in `utils/symbolStore.js`) to survive
  navigating away and back within a session, without a real state library.
  `symbolStore` is intentionally shared between StrikeLab and Charts so
  picking a symbol on one carries over to the other.
- `frontend/src/api/client.js` is a flat set of exported functions around a
  shared `request(path, options)` helper (Bearer auth, redirects to
  `/login` on 401). Follow that pattern for new endpoints rather than
  introducing a second HTTP client.
- `DataTable` (`components/DataTable.jsx`) auto-sorts a column by its raw
  `row[key]` whenever `key` names a real field on the row data — a `render`
  column (formatted date, custom cell) is still sortable as long as `key`
  isn't purely cosmetic (a checkbox column with no backing field correctly
  stays unsortable). Don't reintroduce the old "any `render` column is
  unsortable" rule; that silently broke sorting on several columns once
  before it was fixed.
- `.cell-positive`/`.cell-negative` (green/red P&L text, `tables.css`) are
  scoped as `.data-table td.cell-positive` (class on the `<td>` itself,
  DataTable's own auto-coloring) **and** `.data-table td .cell-positive`
  (class on a `<span>` a custom `render` wraps its text in, for a column
  whose value isn't a plain row field — e.g. a live-quote-derived P&L). Both
  forms exist in this codebase; a bare `.cell-positive` selector silently
  loses to `.data-table td`'s own color rule on specificity, which is why
  both variants are needed rather than one.

## Dev workflow

```bash
# Backend (from repo root)
uv run uvicorn api.app:app --reload

# Frontend (separate terminal)
cd frontend && npm run dev
```

The Vite dev server serves **HTTPS** on `https://127.0.0.1:3000`
(`@vitejs/plugin-basic-ssl`, self-signed) — required for the Schwab
reconnect callback locally (`SCHWAB_APP_CALLBACK_URL=https://127.0.0.1:3000/api/auth/schwab/callback`).
Open the app at that exact origin; `localhost` is a different origin with its
own sessionStorage login.

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
relevant to day-to-day agent work: `CHAIN_PROVIDER`, `SCHWAB_APP_KEY` /
`SCHWAB_APP_SECRET` / `SCHWAB_APP_CALLBACK_URL`, `TASTY_CLIENT_ID` /
`TASTY_CLIENT_SECRET` / `TASTY_REFRESH_TOKEN`, `OPENAI_API_KEY` /
`OPENAI_MODEL`, `SECRET_KEY`, `ADMIN_USERNAME` / `ADMIN_PASSWORD`. Deploy-only (Fly.io, set in `fly.toml`):
`TOKEN_FILE` (where `FileTokenProvider` keeps the Schwab token — `/data/token.json`
on the Fly volume; defaults to `token.json` in the working dir) and
`LOG_TO_STDOUT` (mirror `logs/api.log` to stdout so `fly logs` shows it).
