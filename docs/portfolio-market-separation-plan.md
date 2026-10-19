# Portfolio / Market Separation — Plan

_Drafted 2026-10-19. Status: Tastytrade-as-account-source and Schwab-as-chain-provider removed (2026-10-19); the rest is still a proposal._

## Goal

1. **Portfolio flows** (Positions, Transactions, Reports, and the copilot's
   account tools) use **Schwab only**, with no Tastytrade calls anywhere in
   them.
2. **Market flows** (Analyze, Strategy Builder, Charts, Screener, live
   quotes) are the only code that talks to Tastytrade — and use Tastytrade
   only (Schwab no longer serves chains; done).
3. The backend is laid out so the two are separate by construction:
   separate packages, separate URL prefixes, and an automated check that
   fails if Portfolio code imports Tastytrade.

## Where Portfolio uses Tastytrade today

| # | Use | Where | Why it's there |
|---|---|---|---|
| A | ✅ **Removed 2026-10-19.** Tastytrade **as the account source** (`ACCOUNT_BROKER_PROVIDER=tastytrade`): positions, balances and transactions from a Tastytrade account | `TastytradePositionProvider`, `TastytradeTransactionProvider`, `resolve_tastytrade_account_number` (`service/account_data_providers.py`); the `_native` branches in `PositionService` (`_get_futures_position_native`, `_get_open_futures_option_legs_native`, `_get_futures_option_position_native`) | An alternative account broker. **Unused**: `.env` says `schwab`, and `fly.toml` doesn't set it. |
| B | Live price of **outright futures** on Positions | `PositionService.get_futures_quotes` → `GET /api/positions/futures/quotes` | Schwab has no futures quotes. |
| C | Live price of **futures options** on Positions | `PositionService.get_futures_option_quotes` / `_quote_futures_option_legs` → `GET /api/positions/futures/options/quotes` | Schwab rejects futures-option symbols. |
| D | Live price of **open option legs** in Transactions (unrealized P&L): equity legs and futures-option legs | `TransactionService.get_option_quotes` / `_get_equity_option_quotes` → `GET /api/transactions/options/quotes` | Equity legs could use Schwab; futures-option legs can't. |

Stocks and equity options on Positions are priced by **Schwab's** own quotes
(`SchwabPositionProvider.get_quotes`). No Tastytrade is involved there.

**The constraint that shapes this plan:** Schwab cannot price futures or
futures options at all. So B, C and the futures half of D can't be switched
to Schwab. Those prices have to come from a **Market** endpoint, which is
Tastytrade-backed by design.

## Target design

### The rule

- **Portfolio** returns account facts: positions, balances, trades, realized
  P&L. It may use Schwab's own quotes where Schwab supports them (stocks,
  equity options), since that's still the Portfolio broker.
- **Market** returns prices. Any live price Schwab can't provide (futures,
  futures options) is fetched by the page from a Market quotes endpoint, and
  the page combines it with the Portfolio data. That's already how the
  Positions page computes futures P&L, in the browser.

### Backend layout

```
api/
  portfolio/                 # mounted at /api/portfolio, require_auth (+ Schwab token owner)
    __init__.py              # builds one router from the modules below
    positions.py             # balances, stocks, options, futures, futures options, exposure
    transactions.py          # raw history, option trades, equity/futures round-trips
  market/                    # mounted at /api/market, require_auth
    __init__.py
    chains.py                # expirations, chain
    screener.py
    strategy.py              # templates, build
    history.py               # price history (Charts)
    quotes.py                # NEW: live prices for futures and option contracts
    stream.py                # WebSocket chain stream (was market_stream.py)
  auth.py, admin.py, copilot.py, users.py, app.py   # unchanged

service/
  portfolio/                 # Schwab only. Must never import broker.tastytrade
    positions.py             # PositionService (was service/position.py)
    transactions.py          # TransactionService
    providers/               # ✅ done 2026-10-19: base.py (Protocols), schwab.py, __init__.py (registry)
  market/                    # Tastytrade only
    market.py                # MarketService
    chain_providers.py       # was option_chain_providers.py
    quotes.py                # NEW: QuoteService (logic moved out of PositionService/TransactionService)
    strategy_builder.py, screener_strategies.py
  shared/                    # broker-neutral, imported by both sides
    strategy_math.py
    contracts.py             # contract multipliers, OCC/futures option symbol parsing and formatting
```

`service/__init__.py` keeps re-exporting `PositionService`,
`TransactionService` and `MarketService`, so callers like the copilot's tools
only change where they import from.

### Boundary check

The repo's first automated test, `tests/test_layer_boundaries.py`:
- parses every file under `service/portfolio/` and `api/portfolio/`;
- **fails if any of them imports `broker.tastytrade`**, directly or through
  `service.market`.

It needs `uv add --dev pytest`. That's what keeps the separation from quietly
eroding later.

### New Market quotes endpoint

`POST /api/market/quotes` replaces the three Portfolio quote endpoints (B, C,
D):

```jsonc
// request: what the page needs priced
{
  "futures": ["ES", "NQ"],                       // roots, quoted as today (see open question 4)
  "options": [                                    // equity or futures options
    { "key": "<row id>", "underlying": "/ES", "expiration": "2026-10-23", "strike": 7650, "type": "PUT" },
    { "key": "<row id>", "underlying": "QQQ", "expiration": "2026-10-23", "strike": 700, "type": "PUT" }
  ]
}
// response: anything that couldn't be priced is simply absent
{ "futures": { "ES": 7712.25 }, "options": { "<row id>": { "bid": 18.5, "ask": 19.0, "mid": 18.75 } } }
```

`QuoteService` is today's `_quote_futures_option_legs` and
`_get_equity_option_quotes`, moved over and merged. Behavior stays the same:
- chains are grouped by underlying and expiration, so each chain is fetched
  only once;
- one DXLink snapshot covers all contracts;
- it returns the bid **and** the ask and mid, since the current code returns
  only the bid.

Contracts are described by underlying, expiration, strike and type rather
than a broker symbol, so the endpoint doesn't depend on Schwab's symbol
format.

### Routes

| Today | After |
|---|---|
| `GET /api/positions/` · `/balances` · `/stocks` · `/options` · `/exposure` · `/futures` · `/futures/options` | `GET /api/portfolio/positions/…` (same subpaths) |
| `GET /api/positions/futures/quotes` · `/futures/options/quotes` | **removed** → `POST /api/market/quotes` |
| `GET /api/transactions/` · `/options` · `/equity` | `GET /api/portfolio/transactions/…` |
| `GET /api/transactions/options/quotes` | **removed** → `POST /api/market/quotes` |
| `GET /api/market/…`, `WS /api/market/ws/chain` | unchanged paths, reorganized into `api/market/` |

The SPA and API deploy together, so old paths are dropped outright, with no
aliases.

## Frontend

- **`api/client.js`:** Portfolio functions point at `/api/portfolio/…`. Add
  `getMarketQuotes({ futures, options })`. Remove `getFuturesQuotes`,
  `getFuturesOptionQuotes` and `getOptionQuotes`.
- **Positions:** after the futures positions load, make one
  `getMarketQuotes` call with the futures roots and the open futures-option
  legs (both legs of a grouped ratio spread). Current price and P&L are
  already computed in the browser and stay as they are.
- **Transactions:** build the quote request from the open (`TRADE`) rows and
  price them through `getMarketQuotes`. The unrealized P&L math is unchanged.
- **Reports:** only the endpoint paths change. It uses no live quotes.
- **`RequireSchwab`** keeps wrapping the Portfolio routes. No Market page
  needs Schwab.

## Copilot

Tools keep calling the services, so only imports move. The tool list stays
the same. The account tools are Portfolio and use Schwab only. The market
tools are Market. No tool needs the new quotes endpoint.

## Removals

✅ = done 2026-10-19 (along with Schwab's chain provider and the
`CHAIN_PROVIDER` setting, so Market is Tastytrade only).


- ✅ `TastytradePositionProvider`, `TastytradeTransactionProvider`,
  `resolve_tastytrade_account_number`.
- ✅ `get_account_broker_provider()` and the **`ACCOUNT_BROKER_PROVIDER`**
  setting: drop it from `.env`, the README's env table, its `grep` line, and
  the Fly secrets if set.
- ✅ The three `_native` branches in `PositionService`, and the
  `TastytradeAPIError` handling in Portfolio code.
- ✅ `parse_tastytrade_future_option_symbol` (Market didn't need it).
- The three Portfolio quote endpoints and their service methods (B, C, D).

## Phases

Each phase leaves the app working. Every phase ends with the usual check:
the dev servers, Positions, Transactions and Reports on real data, plus the
Market pages.

1. **Boundary test and shared module.** Add pytest and the boundary test,
   marked expected-to-fail for now. Move `strategy_math.py` and the contract
   helpers into `service/shared/`. No behavior change.
2. **Market quotes.** Add `QuoteService` and `POST /api/market/quotes`,
   ported from the existing Tastytrade quote code. Run the old and new
   endpoints on the same open positions and check they return the same
   prices.
3. **Switch the pages.** Positions and Transactions price through
   `getMarketQuotes`. Delete the three Portfolio quote endpoints and their
   service code.
4. ✅ **Remove the Tastytrade account path.** Done 2026-10-19.
5. **Restructure.** Move modules into `service/portfolio|market|shared` and
   `api/portfolio|market`. Mount `/api/portfolio`. Update `client.js`, the
   copilot imports, `AGENTS.md` and the README. The boundary test now passes,
   and is no longer marked expected-to-fail.

## Open questions

1. **Stock and equity-option prices on Positions:** keep Schwab's quotes
   (recommended: same broker as the account, per user), or move all live
   pricing to the Market endpoint for one consistent source?
2. ✅ **`ACCOUNT_BROKER_PROVIDER`:** decided — removed; the app reads a
   Schwab account only.
3. **URL change:** OK to move `/api/positions` and `/api/transactions` under
   `/api/portfolio` with no aliases? Anything outside the app calling them,
   such as scripts or bookmarks, would break.
4. **Futures quotes:** today a futures position is priced by its *root*,
   which gives the front-month price. Near a roll, a position in the next
   contract month would get the wrong price. The new endpoint could quote
   the exact contract (e.g. `/ESZ26`) instead. Worth fixing as part of this?
