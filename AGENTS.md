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
| `broker/schwab/` | Schwab REST client — **read-only by design**: quotes, positions, transactions, the account list. (Price history and option chains were removed — market data is Tastytrade's.) No order-placement code exists here at all. |
| `broker/tastytrade/` | Tastytrade REST + DXLink WebSocket client — instruments, chains, live quotes/greeks/candles via streaming. **Read-only by design**: no account, order or trading methods, and no POST/PUT/DELETE request helpers — see Guardrails below. |
| `service/` | Business logic, in three packages kept apart by `tests/test_layer_boundaries.py`. **`portfolio/`** (each user's chosen broker — Schwab is the only one registered today; never imports `broker.tastytrade` or `service.market`): `PositionService` (`positions.py`; fetches the account snapshot lazily, so futures endpoints never hit Schwab's positions API), `TransactionService` (`transactions.py`), `providers/` (the broker seam — see "Adding a Portfolio broker" below), `models.py` (typed rows — the services' return types and the API's `response_model`s; plain numbers, `None` when unknown, never pre-formatted strings), and the domain logic as pure functions: `option_matching.py` (open/close matching + CLOSED/EXPIRED/ASSIGNED/EXERCISED), `equity_matching.py` (FIFO round-trips), `ratio_spreads.py`, `date_windows.py` (named lookback windows). **`market/`** (Tastytrade only — never imports Portfolio or Schwab): `MarketService` (`market.py` — a thin facade over the modules below), `chain_providers.py`, `screener.py` (the Screener's ranking: `short_option_row`/`long_option_row`, `screen_options`), `history.py` (Charts' candles via DXLink, `RANGE_PARAMS`, swing support/resistance, the per-(symbol, range) cache), `errors.py` (`SymbolNotFound` → 404, `MarketDataError` → 502 with a fixed message; `translate_errors()` is the one place broker exceptions become these — `api/app.py` registers the handlers), `models.py` (the routes' `response_model`s), `quotes.py` (`QuoteService` — live prices for contracts described as underlying/expiration/strike/type), `strategy_builder.py` (the Analyze page's Strategy Builder: data-driven templates, adding a strategy = one `TEMPLATES` entry, solved against one expiration's chain at mid prices; a template's `shares` — Covered Call's 100 per contract — enters the payoff as a `STOCK` leg entered at spot, in `strategy_math.py` and the Analyze page's `utils/payoffMath.js` alike), `screener_strategies.py` (the Screener's multi-leg rows: every combination of a credit template at natural prices, capital = max loss, or for unlimited upside the downside loss + spot per uncovered short call; `COMBO_BUDGET` caps the search per expiration). **`shared/`** (broker-neutral, imported by both): `strategy_math.py` (payoff math for the builder and screener), `contracts.py` (contract multipliers, OCC symbol parsing). `service/__init__.py` re-exports the four services. This is the layer both the REST API and the copilot's tools call into — reuse it rather than reaching into `broker/` directly. |
| `api/` | FastAPI routers: `auth.py`, `admin.py`, `copilot.py`; `portfolio/` (mounted at `/api/portfolio`: `positions.py`, `transactions.py`) and `market/` (mounted at `/api/market`: `chains.py`, `screener.py`, `strategy.py`, `history.py`, `quotes.py` — `POST /api/market/quotes` — and `stream.py`, the WebSocket at `/api/market/ws`; `params.py`'s `Symbol` type validates and upper-cases every symbol parameter, so use it on any new Market route). Registered in `api/app.py`; unknown `/api` paths are a 404, not the SPA's `index.html`. |
| `copilot/` | The read-only financial-copilot agent — see its own section below. |
| `frontend/src/pages/` | `Home` (`/home`, where login lands: what to trade today, new income first — capacity incl. an estimated /ES and /NQ futures margin (`home.futures_margin_pct` of notional, since Schwab's API doesn't report it), month-to-date P&L, /ES and /NQ short-option ideas from the Screener ranked by return on margin, shares to sell against, take-profit, expiring shorts with moneyness, expiry calendar, concentration, and a margin-cushion stress test that reprices every option in full at its Tastytrade implied volatility (plus `home.stress_iv_rise` points per 10% drop), margins futures per root like SPAN and never lets a requirement fall — deliberately cautious, keep it that way; rules are `home.*` in `config/app.properties`, the logic is the pure, tested `utils/homeInsights.js`), `Landing` (public page at `/`; Log in / Register open as overlays on it, and `/login` — where `ProtectedRoute` sends logged-out visitors, remembering the page they wanted — is the same page with the login overlay open. Its screenshots in `frontend/public/landing/` are real captures, and since the page is public they must never show real account data or the real user: market-data pages (Screener, Analyze/Strategy Builder, Charts) are shot on live market data, and the hero's Reports shot uses **sample P&L** via mocked API responses, with the sidebar user mocked as "Demo Trader" — never capture Positions/Transactions/Reports on real data. Register only explains that the admin creates accounts — there's no self-service sign-up), `Positions`, `Transactions`, `Reports`, `StrikeLab` (routed as `/analyze`), `Charts`, `Screener` (top puts/calls to sell across tickers, ranked by annualized ROI — backed by `MarketService.screen_options` + each chain provider's `get_screener_contracts`; multi-leg combinations are every multi-leg **credit** Strategy Builder template, generated from `TEMPLATES` in `service/market/screener_strategies.py` — so a new credit template appears in the Screener automatically, and the page's dropdown comes from `GET /api/market/options/screener/strategies`), `Settings` (account/change password, Schwab connection, light/dark theme — not in the navbar — and the admin-only Users card, `components/AccountSettings.jsx`), `Login`. |
| `frontend/src/components/` | `Navbar`, `CopilotWidget` (floating chat, mounted globally in `App.jsx`), `DataTable`, `ErrorBoundary`, `RequireSchwab` (wraps the Portfolio routes in `App.jsx`: checks the user's Schwab connection first and shows a connect/reconnect notice instead of the page when it's missing or expired — wrap any new page that reads Schwab account data the same way), `LoginCard` (the login form, used by the landing page's overlay), `HelpTip` ("?" button + pop-up beside a form label — use it for field help text instead of a paragraph under the form), `ReportViews` (the Reports page's views — key numbers, P&L calendars, running totals, per-symbol and symbol-by-month tables; the math is in `utils/reportStats.js`, the gain/loss heat colors are the `--pnl-*` tokens), `StrategyBuilderOverlay` (the Analyze page's "Build Strategy" overlay — its form is generated from `GET /api/market/strategies`; applied legs go through StrikeLab's `applyLegs`, which the copilot Apply also uses), `Spinner`, `ProtectedRoute`. |
| `frontend/src/context/` | `AuthContext`, `ThemeContext` (dark mode). |
| `frontend/src/utils/` | Small shared helpers, not page-specific: `optionSymbol.js` (the one canonical "TICKER MM/DD/YYYY STRIKE.00 P/C" formatter — every page showing an option contract should call this, not re-derive its own), `dateFormat.js` (MM/DD/YYYY), `contractMultiplier.js` (equity=100 vs futures-root multipliers + `isFuturesRoot`), `copilotContext.js` (see Copilot section below), `symbolStore.js` (see below). |
| `scripts/tos_statement_pl.py` | Independent check on the Reports page: realized P&L computed from a thinkorswim Account Statement CSV alone (`uv run python -m scripts.tos_statement_pl STATEMENT.csv OUTDIR`). Its method differs from Reports by design (futures marked to market, fees and income included, nothing from before the statement start) — the module docstring lists how; it also rebuilds calendar rolls the export garbles. Tested in `tests/test_tos_statement_pl.py`. |
| `config/app.properties` | Application-level choices (`key=value`): ratio-spread grouping (`trades.group_ratio_spreads` — Positions, the copilot, and the Transactions page's default), Transactions' default view, the futures positions lookback, the transaction-matching padding (how far around a requested range trades are fetched — Schwab's one-year request cap, `MAX_SPAN_DAYS`, stays in `service/portfolio/date_windows.py`), the copilot's default history window. `utils/app_config.py` holds the schema (`SETTINGS`: type, default, allowed values) and rejects unknown keys or bad values at startup; read with `get_config()[key]`. Settings the browser needs are in `PUBLIC_SETTINGS`, served by `GET /api/config`. Adding a setting = one `SETTINGS` entry + a commented line in the file. Not for secrets — those stay env vars. |
| `frontend/src/styles/tokens.css` | All design tokens (colors, spacing, shadows) as CSS custom properties, including the dark-theme palette under `:root[data-theme="dark"]`. Every other stylesheet should reference tokens, not hardcode colors — a hardcoded color is the single most common way a change quietly breaks dark mode. |

## Guardrails — read before touching trading logic

- **Never add order placement, cancellation or account access to
  `TastytradeClient`** (or wire one into a service, API route, or the
  copilot's tools). The client was deliberately stripped to market data —
  its order methods and POST/PUT/DELETE helpers were deleted. Tastytrade
  also defaults to the **production** endpoint, not sandbox — a real key
  there acts on a real account.
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
  `EXERCISED`, which, like an equity `ASSIGNED`, **keeps its premium as P&L**
  (zeroing it would drop the premium from the total, since the future /
  shares are booked at the strike — thinkorswim counts it the same way).
  Reports counts `EXERCISED` and `ASSIGNED` in net P&L but not in win rate /
  avg win-loss / profit factor. Any code listing "closed" types must
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
  equity options on Positions are still priced by Schwab's own quotes;
  their Theta column (like the futures-option tables') comes from the same
  `POST /api/market/quotes` call, whose option quotes carry per-share
  `theta` from DXLink's Greeks event.
  DXLink's history depth varies by bar size (monthly: decades;
  daily: ~2 years; weekly: only months) and repeat long-history requests
  can come back empty, which is why 5Y/MAX use monthly bars and
  `MarketService` caches results per (symbol, range).

## Adding a Portfolio broker

Portfolio flows read the broker through `service/portfolio/providers/`:
`base.py` holds the Protocols (`PositionProvider`: snapshot, quotes,
`list_accounts`; `TransactionProvider`: raw history, option legs,
equity/futures legs, income and fees, futures-root normalization) and the
`OptionTransaction` leg model (broker-neutral helpers — contract multipliers,
OCC parsing — are in `service/shared/contracts.py`); `schwab.py` is the only
implementation; `__init__.py` is the registry (`register()`,
`DEFAULT_BROKER`). **Each user picks their broker in Settings**
(`components/BrokerPicker.jsx`, via `GET /api/portfolio/positions/brokers`
and `PUT .../broker`; saved as `broker` in SQLite, `api/users.set_broker`,
which also clears the chosen account). `require_auth` puts it on the request
(`broker.request_context.set_selected_broker`) and `get_broker()` resolves it,
falling back to `DEFAULT_BROKER` when unset or no longer registered.
`PositionService`, `TransactionService`, the API routes and the pages never
name a broker. Market data stays Tastytrade-only and is not part of this seam.

**Checklist for a new broker** (`<broker>` below is its registry name, e.g.
`tastytrade`):

1. **Read-only client** in `broker/<broker>/`: GET requests only — no order
   placement, cancellation, transfers or any POST/PUT/DELETE helper (same rule
   as the Guardrails above). Raise `broker.exceptions` types. Add a test that
   the client has no write methods.
2. **Per-user credentials**, never one shared account: store each user's
   tokens keyed by user id, like `broker/schwab/auth/token_provider.py`
   (`set_token_owner` from `require_auth`, and a call with no owner raises
   instead of falling back to someone else's account). Never log tokens or
   response bodies.
3. **Connect flow**: start / callback / status routes beside
   `/api/auth/schwab/*` in `api/auth.py` (a signed `state` for the callback,
   as Schwab's), and a connection card on the Settings page. Settings shows
   the Schwab card today; show the card for the user's chosen broker.
4. **Provider module** `service/portfolio/providers/<broker>.py` with classes
   implementing both Protocols in `base.py`, returning exactly the shapes its
   docstrings give. Keep every broker specific inside it (SDK models, symbol
   formats, how expirations / assignments / exercises are recorded →
   `close_event`, which records are transfers rather than trades), and honor
   `get_selected_account()` from `list_accounts()`. Points that have bitten
   Schwab and need checking for any broker:
   - ETFs and stocks are both `"EQUITY"`; a share transfer is not a fill.
   - `position_effect` (OPENING/CLOSING) on stock fills, for the matcher.
   - Futures: return them if the broker's positions API has them (Schwab's
     doesn't, so `PositionService` rebuilds them from history).
   - `fetch_income_and_fees`: dividends, interest and per-trade fees, signed.
   - Per-position and account `maintenance_requirement`.
   - Whether its average price folds an assigned option's premium into the
     share cost (Schwab's does — see `PositionService.get_stock_trade_basis`).
   - A request window longer than the broker allows: split it in the provider.
5. **Register it**: one `register(PortfolioBroker("<broker>", "<Label>",
   PositionsClass, TransactionsClass))` line in `providers/__init__.py`. It
   then appears in Settings' broker choice automatically.
6. **Connection check** for the Portfolio pages: `RequireSchwab` wraps them in
   `App.jsx`; generalise it to check the chosen broker's connection.
7. **Tests**: parsing tests for its records (like `tests/test_schwab_parsing.py`,
   with stand-in clients — no network), and a run of the existing service
   tests through a stand-in provider. Update `tests/test_layer_boundaries.py`
   only as narrowly as the broker needs.
8. **Docs**: its env vars in the README, and this file.

A **Tastytrade** portfolio broker means changing the Tastytrade guardrail
above on purpose: a separate, read-only accounts client with each user's own
credentials (steps 1–2), never account calls added to the market-data
`TastytradeClient`, and never the shared `TASTY_*` env credentials, which are
for market data. Its API already covers positions (futures included),
balances, per-underlying margin (`/margin/accounts/{n}/requirements`) and
transactions.

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
(saved per user in SQLite, chosen with `components/AccountPicker.jsx` — right-aligned
above every Portfolio page, mounted by `RequireSchwab`, which remounts the
page on a switch — and in Settings, via `GET /api/portfolio/positions/accounts` and
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
  the screener, chain provider, strategy builder, price history and error
  translation (stand-ins in `tests/market_helpers.py`),
  API input validation (`test_transactions_api.py`, `test_market_api.py`), and the Portfolio/Market import boundary
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
`LOG_TO_STDOUT` (mirror `logs/api.log` to stdout so `fly logs` shows it). Optional: `APP_PROPERTIES` (path to a properties file to use instead of `config/app.properties`).
