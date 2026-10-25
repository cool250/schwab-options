const BASE = '/api'

function getToken() {
  return sessionStorage.getItem('auth_token')
}

async function request(path, options = {}) {
  const token = getToken()
  const headers = { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) }
  const res = await fetch(`${BASE}${path}`, { ...options, headers, cache: 'no-store' })
  if (res.status === 401) {
    sessionStorage.removeItem('auth_token')
    sessionStorage.setItem('auth_notice', 'Your session expired. Please log in again.')
    window.location.href = '/login'
    throw new Error('Session expired. Please log in again.')
  }
  if (!res.ok) {
    const text = await res.text()
    let message = text || res.statusText
    try {
      const json = JSON.parse(text)
      // A validation error (422) lists each bad field: [{loc, msg}, ...].
      if (Array.isArray(json.detail)) {
        message = json.detail.map((d) => `${d.loc?.[d.loc.length - 1] ?? 'input'}: ${d.msg}`).join('; ')
      } else if (json.detail) {
        message = json.detail
      }
    } catch {}
    const err = new Error(message)
    err.status = res.status
    throw err
  }
  return res.json()
}

// The backend maps a dead Schwab session (refresh token expired, or Schwab
// itself rejecting re-auth) to 503 — see api/app.py's BrokerAuthError
// handler. That's a broker-side outage, not something re-logging into this
// app fixes, so callers surface it as a distinct message instead of the
// generic "API server is down" one.
export const BROKER_AUTH_MESSAGE =
  'Broker authentication failed — Schwab isn\'t connected or its login has expired. Reconnect Schwab in Settings.'

// The backend maps any other broker-side failure (e.g. Schwab itself
// returning 503s after retries) to 502 — see api/app.py's BrokerError
// handler. Distinct from BROKER_AUTH_MESSAGE: this isn't something
// re-authenticating fixes, just an outage to wait out.
export const SYSTEM_ERROR_MESSAGE =
  'System error — the broker service is temporarily unavailable. Please try again shortly.'

export function isBrokerAuthError(err) {
  return err?.status === 503
}

export function isSystemError(err) {
  return err?.status === 502
}

export function friendlyErrorMessage(err, fallback) {
  if (isBrokerAuthError(err)) return BROKER_AUTH_MESSAGE
  if (isSystemError(err)) return SYSTEM_ERROR_MESSAGE
  return fallback
}

export function getOptionChain(symbol, dte) {
  const p = new URLSearchParams({ symbol, dte })
  return request(`/market/options/chain?${p}`)
}

export function getExpirationList(symbol, daysAhead = 60) {
  const p = new URLSearchParams({ symbol, days_ahead: daysAhead })
  return request(`/market/options/expiration-list?${p}`)
}

export function screenOptions({ symbols, minDte, maxDte, minMoneyness, maxMoneyness, minDelta, maxDelta, strategy }) {
  const p = new URLSearchParams({
    symbols: symbols.join(','),
    min_dte: minDte,
    max_dte: maxDte,
    min_moneyness: minMoneyness,
    max_moneyness: maxMoneyness,
    strategy,
  })
  // Delta bounds are optional — null means "no limit on that side", so
  // leave the param off entirely rather than sending "null".
  for (const [key, value] of Object.entries({ min_delta: minDelta, max_delta: maxDelta })) {
    if (value != null) p.set(key, value)
  }
  return request(`/market/options/screener?${p}`)
}

// The Screener's strategy choices: [{ id, name, kind: 'short' | 'long' | 'combo' }]
// — the multi-leg ones are the Strategy Builder's credit templates.
export function getScreenerStrategies() {
  return request('/market/options/screener/strategies')
}

// Strategy Builder (Analyze page overlay) — see service/market/strategy_builder.py.
export function getStrategyTemplates() {
  return request('/market/strategies')
}

// params: { [legKey]: { mode, value } }; target: per-share min credit / max
// debit, or null for none.
// maxDte: optional end of an expiration range (builds on every listed
// expiration from dte through maxDte).
export function buildStrategy({ symbol, dte, expirationDate, maxDte, strategy, params, target }) {
  return request('/market/strategy/build', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, dte, expirationDate, maxDte, strategy, params, target }),
  })
}

// Current user / session renewal / own password — see api/auth.py.
export function refreshSession() {
  return request('/auth/refresh', { method: 'POST' })
}

// Application settings from config/app.properties (utils/app_config.py's
// PUBLIC_SETTINGS), e.g. { "trades.group_ratio_spreads": true }.
export function getAppConfig() {
  return request('/config')
}

export function getMe() {
  return request('/auth/me')
}

// Your own optional profile (first/last name, email); blank clears a field.
export function updateProfile({ firstName, lastName, email }) {
  return request('/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ firstName, lastName, email }),
  })
}

export function changePassword(currentPassword, newPassword) {
  return request('/auth/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ currentPassword, newPassword }),
  })
}

// Admin user management (Settings → Users) — see api/admin.py.
export function listUsers() {
  return request('/admin/users')
}

export function createUser(username, password, isAdmin = false, profile = {}) {
  const { firstName, lastName, email } = profile
  return request('/admin/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, isAdmin, firstName, lastName, email }),
  })
}

export function resetUserPassword(userId, password) {
  return request(`/admin/users/${userId}/password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
}

export function setUserDisabled(userId, disabled) {
  return request(`/admin/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disabled }),
  })
}

export function deleteUser(userId) {
  return request(`/admin/users/${userId}`, { method: 'DELETE' })
}

// Schwab reconnect (Settings) — see api/auth.py's /schwab/* routes.
export function getSchwabStatus() {
  return request('/auth/schwab/status')
}

export function startSchwabReconnect() {
  return request('/auth/schwab/start')
}

// Brokers Portfolio data can come from — [{ name, label, selected }] — and
// choosing which one Positions, Transactions and Reports read (saved per user).
export function getBrokers() {
  return request('/portfolio/positions/brokers')
}

export function setBroker(name) {
  return request('/portfolio/positions/broker', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

// Accounts the broker login covers — [{ id, label: "…6112", type, value,
// positions, selected }] — and choosing which one Portfolio pages read.
export function getAccounts() {
  return request('/portfolio/positions/accounts')
}

export function setAccount(id) {
  return request('/portfolio/positions/account', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
}

export function getPriceHistory(symbol, range = '1M') {
  const p = new URLSearchParams({ symbol, range })
  return request(`/market/price-history?${p}`)
}

export function getPositions() {
  return request('/portfolio/positions/')
}

// { [symbol]: per-share price of each stock position as its fills were
// priced, or null } — without assigned options' premium folded in.
export function getStockTradeBasis() {
  return request('/portfolio/positions/stocks/trade-basis')
}

export function getFuturesPosition() {
  return request('/portfolio/positions/futures')
}

export function getFuturesOptionPosition() {
  return request('/portfolio/positions/futures/options')
}

export function getOptionTransactions(stockTicker, startDate, endDate, contractType, realizedGainsOnly, unrealizedOnly = false, groupRatioSpreads = true) {
  const p = new URLSearchParams({
    stock_ticker: stockTicker,
    start_date: startDate,
    end_date: endDate,
    contract_type: contractType,
    realized_gains_only: realizedGainsOnly,
    unrealized_only: unrealizedOnly,
    group_ratio_spreads: groupRatioSpreads,
  })
  return request(`/portfolio/transactions/options?${p}`)
}

// Live prices for what Schwab can't quote (futures, futures options) and
// open option legs — from Market (Tastytrade), combined with Portfolio rows
// in the page. Anything that couldn't be priced is absent from the result.
//   futures: ['ES', 'NQ']
//   options: [{ key, underlying, expiration: 'YYYY-MM-DD', strike, type: 'PUT'|'CALL' }]
// -> { futures: { ES: 7712.25 }, options: { [key]: { bid, ask, mid } } }
export function getMarketQuotes({ futures = [], options = [] }) {
  return request('/market/quotes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ futures, options }),
  })
}

// { [key]: { bid, ask, mid, theta } } for option contracts (theta per share,
// per day); contracts that couldn't be priced are absent.
export async function getOptionQuotes(options) {
  if (!options.length) return {}
  const { options: quotes } = await getMarketQuotes({ options })
  return quotes
}

// { [key]: bid } for option contracts — the price Positions and
// Transactions value open legs at.
export async function getOptionBids(options) {
  if (!options.length) return {}
  const { options: quotes } = await getMarketQuotes({ options })
  const bids = {}
  for (const [key, q] of Object.entries(quotes)) if (q.bid != null) bids[key] = q.bid
  return bids
}

// Dividends, interest and trading fees, start..end inclusive:
// [{ date, kind: 'INCOME'|'FEE', category, description, amount }] (amount signed).
export function getIncomeAndFees(startDate, endDate) {
  const p = new URLSearchParams({ start_date: startDate, end_date: endDate })
  return request(`/portfolio/transactions/income-fees?${p}`)
}

export function getEquityTransactions(stockTicker, startDate, endDate, assetType, realizedGainsOnly) {
  const p = new URLSearchParams({
    stock_ticker: stockTicker,
    start_date: startDate,
    end_date: endDate,
    asset_type: assetType,
    realized_gains_only: realizedGainsOnly,
  })
  return request(`/portfolio/transactions/equity?${p}`)
}

export function sendCopilotMessage(messages, context) {
  return request('/copilot/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, context: context?.page ? context : undefined }),
  })
}

export function getAllocations(startDate, endDate, realizedGainsOnly) {
  const p = new URLSearchParams({
    stock_ticker: '',
    start_date: startDate,
    end_date: endDate,
    contract_type: 'ALL',
    realized_gains_only: realizedGainsOnly,
    // Reports dates P&L by day: a ratio spread whose legs closed on
    // different days must keep each leg's own close date, not the merged
    // record's last one (that moved a 9/29 loss into October once).
    group_ratio_spreads: false,
  })
  return request(`/portfolio/transactions/options?${p}`)
}
