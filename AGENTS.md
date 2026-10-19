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
| `broker/schwab/` | Schwab REST client — **read-only by design**: quotes, price history and option chains (neither used by the app any more — market data is Tastytrade's), positions, transactions. No order-placement code exists here at all. |
| `broker/tastytrade/` | Tastytrade REST + DXLink WebSocket client — chains, live quotes/greeks via streaming. Has `place_order`/`cancel_order`/`get_orders` methods that exist in the SDK but are **never called anywhere in the app** — see Guardrails below. |
| `service/` | Business logic, in three packages kept apart by `tests/test_layer_boundaries.py`. **`portfolio/`** (Schwab only — never imports `broker.tastytrade` or `service.market`): `PositionService` (`positions.py`; fetches the account snapshot lazily, so futures endpoints never hit Schwab's positions API), `TransactionService` (`transactions.py`), `providers/` (the broker seam — see "Adding a Portfolio broker" below), `models.py` (typed rows — the services' return types and the API's `response_model`s; plain numbers, `None` when unknown, never pre-formatted strings), and the domain logic as pure functions: `option_matching.py` (open/close matching + CLOSED/EXPIRED/ASSIGNED/EXERCISED), `equity_matching.py` (FIFO round-trips), `ratio_spreads.py`, `date_windows.py` (named lookback windows). **`market/`** (Tastytrade only — never imports Portfolio or Schwab): `MarketService` (`market.py`), `chain_providers.py`, `quotes.py` (`QuoteService` — live prices for contracts described as underlying/expiration/strike/type), `strategy_builder.py` (the Analyze page's Strategy Builder: data-driven templates, adding a strategy = one `TEMPLATES` entry, solved against one expiration's chain at mid prices), `screener_strategies.py`. **`shared/`** (broker-neutral, imported by both): `strategy_math.py` (payoff math for the builder and screener), `contracts.py` (contract multipliers, OCC symbol parsing). `service/__init__.py` re-exports the four services. This is the layer both the REST API and the copilot's tools call into — reuse it rather than reaching into `broker/` directly. |
| `api/` | FastAPI routers: `auth.py`, `admin.py`, `copilot.py`; `portfolio/` (mounted at `/api/portfolio`: `positions.py`, `transactions.py`) and `market/` (mounted at `/api/market`: `chains.py`, `screener.py`, `strategy.py`, `history.py`, `quotes.py` — `POST /api/market/quotes` — and `stream.py`, the WebSocket at `/api/market/ws`). Registered in `api/app.py`; unknown `/api` paths are a 404, not the SPA's `index.html`. |
| `copilot/` | The read-only financial-copilot agent — see its own section below. |
| `frontend/src/pages/` | `Landing` (public page at `/`; Log in / Register open as overlays on it, and `/login` — where `ProtectedRoute` sends logged-out visitors, remembering the page they wanted — is the same page with the login overlay open. Its screenshots in `frontend/public/landing/` are real captures, and since the page is public they must never show real account data or the real user: market-data pages (Screener, Analyze/Strategy Builder, Charts) are shot on live market data, and the hero's Reports shot uses **sample P&L** via mocked API responses, with the sidebar user mocked as "Demo Trader" — never capture Positions/Transactions/Reports on real data. Register only explains that the admin creates accounts — there's no self-service sign-up), `Positions`, `Transactions`, `Reports`, `StrikeLab` (routed as `/analyze`), `Charts`, `Screener` (top puts/calls to sell across tickers, ranked by annualized ROI — backed by `MarketService.screen_options` + each chain provider's `get_screener_contracts`; multi-leg Ratio Put / Jade Lizard combinations are built in `service/market/screener_strategies.py`), `Settings` (account/change password, Schwab connection, light/dark theme — not in the navbar — and the admin-only Users card, `components/AccountSettings.jsx`), `Login`. |
| `frontend/src/components/` | `Navbar`, `CopilotWidget` (floating chat, mounted globally in `App.jsx`), `DataTable`, `ErrorBoundary`, `RequireSchwab` (wraps the Portfolio routes in `App.jsx`: checks the user's Schwab connection first and shows a connect/reconnect notice instead of the page when it's missing or expired — wrap any new page that reads Schwab account data the same way), `LoginCard` (the login form, used by the landing page's overlay), `HelpTip` ("?" button + pop-up beside a form label — use it for field help text instead of a paragraph under the form), `ReportViews` (the Reports page's views — key numbers, P&L calendars, running totals, per-symbol and symbol-by-month tables; the math is in `utils/reportStats.js`, the gain/loss heat colors are the `--pnl-*` tokens), `StrategyBuilderOverlay` (the Analyze page's "Build Strategy" overlay — its form is generated from `GET /api/market/strategies`; applied legs go through StrikeLab's `applyLegs`, which the copilot Apply also uses), `Spinner`, `ProtectedRoute`. |
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
  tools. `TransactionService.get_option_transactions`/`get_equity_transactions`
  and `QuoteService` strip a leading `/` before matching against Schwab's internally-normalized
  bare-root symbols — if you add a new ticker-filtering code path, make sure
  it accepts both forms, or it'll silently return zero results for a
  perfectly valid futures query (this exact bug shipped once already).
- **Schwab books futures-option exercises and expirations as ordinary
  `TRADE`s**, not the `RECEIVE_AND_DELIVER` "Removed due to …" records equity
  options get: the option closes at $0 ("Exercise, future settle …" /
  "Removal of option due to expiration of …") and the delivered future is a
  separate fill at the strike. `SchwabTransactionProvider._identify_close_event`
  maps these to `EXERCISE`/`EXPIRATION`, and the matched leg's type is
  `EXERCISED`, which, unlike an equity `ASSIGNED`, **keeps its premium as P&L**
  (zeroing it would drop the premium from the total, since the future is
  booked at the strike). Reports counts `EXERCISED` in net P&L but not in win
  rate / avg win-loss / profit factor. Any code listing "closed" types must
  include `EXERCISED` alongside `CLOSED`/`EXPIRED`/`ASSIGNED`.
- **One broker per side.** Portfolio data (positions, balances,
  transactions) is **Schwab only**; market data (option chains, the
  screener, the strategy builder, Charts' price history via DXLink `Candle`
  events / `TastytradeClient.get_candles`) is **Tastytrade only**. There's no
  setting to swap either (the old `ACCOUNT_BROKER_PROVIDER` and
  `CHAIN_PROVIDER` switches are gone). Schwab can't quote futures or
  futures options at all, so Positions and Transactions get those prices
  (and open option legs') from `POST /api/market/quotes` and combine them
  with the Portfolio rows **in the page** — Portfolio code never calls
  Tastytrade (`tests/test_layer_boundaries.py` fails if it does). Stocks and
  equity options on Positions are still priced by Schwab's own quotes.
  DXLink's history depth varies by bar size (monthly: decades;
  daily: ~2 years; weekly: only months) and repeat long-history requests
  can come back empty, which is why 5Y/MAX use monthly bars and
  `MarketService` caches results per (symbol, range).

## Adding a Portfolio broker

Portfolio flows read the broker through `service/portfolio/providers/`:
`base.py` holds the Protocols (`PositionProvider`: snapshot, quotes,
`list_accounts`; `TransactionProvider`: raw history, option legs,
equity/futures legs, futures-root normalization) and the `OptionTransaction`
leg model (broker-neutral helpers — contract multipliers, OCC parsing — are
in `service/shared/contracts.py`); `schwab.py` is the only implementation;
`__init__.py` is the registry (`register()`, `ACTIVE_BROKER`). A new broker
is a new module implementing both Protocols plus one `register()` line —
`PositionService`, `TransactionService` and the API routes don't change.
Keep broker specifics (SDK models, symbol formats, how expirations /
assignments / exercises are recorded → `close_event`) inside its module,
raise `broker.exceptions` types, and honor `get_selected_account()`. It
also needs its own connect flow and credential storage (Schwab's are
`/api/auth/schwab/*` and `broker/schwab/auth`). Market data stays
Tastytrade-only and is not part of this seam.

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
work via `contextvars.copy_context().run` (one copy per task). (Market
code's pools, e.g. `MarketService.screen_options`, don't need it — they
only call Tastytrade.) Never cache account data at module
level — services are built per request, and that's what keeps users apart.

**Multiple accounts.** One broker login can cover several accounts.
`require_auth` also calls `broker.request_context.set_selected_account(user.broker_account)`
(saved per user in SQLite, chosen with `components/AccountPicker.jsx` — top
of Positions and in Settings — via `GET /api/portfolio/positions/accounts` and
`PUT /api/portfolio/positions/account`), and the broker client reads it when resolving
the account (Schwab: `Accounts._initialize_account_hash`), falling back to
the broker's first when none is chosen or the chosen one is no longer
authorized. Full account numbers never go to the browser: it gets a masked
label and the provider's opaque id.

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
- `group_ratio_spreads()` (closed/historical trades) and
  `group_open_ratio_spreads()` (currently-open legs, used by the Positions
  page's futures-option tables) both merge matched trade legs that form a
  ratio spread into one record — same qualification rules (exactly two
  strikes, one side net long/short, whole-number ratio ≥ 2), same internal
  consistency guard (total P&L for closed, total quantity for open) that
  falls back to the ungrouped result rather than risk silently misstating a
  number. Both live in `service/portfolio/ratio_spreads.py` (covered by
  `tests/test_ratio_spreads.py`); if you touch either, keep that guard.
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

- **The API returns numbers; the UI formats them.** Portfolio rows
  (`service/portfolio/models.py`) carry plain numbers and `None` for
  unknown — no "$1,234.00" strings. Format in the page (`utils/numberFormat.js`:
  `money`, `count`), and show unknown as "—", never "$0".
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
- Tests: `uv run pytest` (`tests/`, well under a second). They cover the
  Portfolio money math — option matching (closed / expired / assigned /
  exercised, partial and split fills), equity & futures FIFO, ratio-spread
  grouping, Schwab record classification, position pricing — plus Market
  quote matching (`test_market_quotes.py`, a stand-in Tastytrade client),
  API input validation, and the Portfolio/Market import boundary
  (`test_layer_boundaries.py`), all through stand-ins
  (`tests/conftest.py`), so no broker or login is needed. Add a test with any change to that logic; for
  UI or live-broker behavior, still run the dev servers and exercise it.
- Logs: `logs/api.log` (rotating), useful for debugging live broker/DXLink
  behavior — `--log-level debug` on uvicorn surfaces the raw WebSocket
  frames, which has been the fastest way to diagnose several past bugs here. Never log
  credentials or account data at any level: Schwab token responses and
  response bodies are deliberately not logged (only sizes), since logs reach
  `fly logs`.

## Key env vars

See the README's env var table for the full deployment list. The ones most
relevant to day-to-day agent work: `SCHWAB_APP_KEY` /
`SCHWAB_APP_SECRET` / `SCHWAB_APP_CALLBACK_URL`, `TASTY_CLIENT_ID` /
`TASTY_CLIENT_SECRET` / `TASTY_REFRESH_TOKEN`, `OPENAI_API_KEY` /
`OPENAI_MODEL`, `SECRET_KEY`, `ADMIN_USERNAME` / `ADMIN_PASSWORD`. Deploy-only (Fly.io, set in `fly.toml`):
`TOKEN_FILE` (where `FileTokenProvider` keeps the Schwab token — `/data/token.json`
on the Fly volume; defaults to `token.json` in the working dir) and
`LOG_TO_STDOUT` (mirror `logs/api.log` to stdout so `fly logs` shows it).
