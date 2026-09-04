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
    window.location.href = '/login'
    throw new Error('Session expired. Please log in again.')
  }
  if (!res.ok) {
    const text = await res.text()
    let message = text || res.statusText
    try {
      const json = JSON.parse(text)
      if (json.detail) message = json.detail
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
  'Broker authentication failed — the Schwab refresh token has expired. Please re-authenticate.'

export function isBrokerAuthError(err) {
  return err?.status === 503
}

export function friendlyErrorMessage(err, fallback) {
  return isBrokerAuthError(err) ? BROKER_AUTH_MESSAGE : fallback
}

export function getOptionChain(symbol, dte) {
  const p = new URLSearchParams({ symbol, dte })
  return request(`/market/options/chain?${p}`)
}

export function getExpirationList(symbol, daysAhead = 60) {
  const p = new URLSearchParams({ symbol, days_ahead: daysAhead })
  return request(`/market/options/expiration-list?${p}`)
}

export function getPriceHistory(symbol, days = 30) {
  const p = new URLSearchParams({ symbol, days })
  return request(`/market/price-history?${p}`)
}

export function getPositions() {
  return request('/positions/')
}

export function getFuturesPosition() {
  return request('/positions/futures')
}

export function getFuturesOptionPosition() {
  return request('/positions/futures/options')
}

export function getFuturesOptionQuotes() {
  return request('/positions/futures/options/quotes')
}

export function getOptionTransactions(stockTicker, startDate, endDate, contractType, realizedGainsOnly, unrealizedOnly = false) {
  const p = new URLSearchParams({
    stock_ticker: stockTicker,
    start_date: startDate,
    end_date: endDate,
    contract_type: contractType,
    realized_gains_only: realizedGainsOnly,
    unrealized_only: unrealizedOnly,
    group_ratio_spreads: true,
  })
  return request(`/transactions/options?${p}`)
}

export function getOptionQuotes(stockTicker, startDate, endDate, contractType) {
  const p = new URLSearchParams({
    stock_ticker: stockTicker,
    start_date: startDate,
    end_date: endDate,
    contract_type: contractType,
  })
  return request(`/transactions/options/quotes?${p}`)
}

export function getEquityTransactions(stockTicker, startDate, endDate, assetType, realizedGainsOnly) {
  const p = new URLSearchParams({
    stock_ticker: stockTicker,
    start_date: startDate,
    end_date: endDate,
    asset_type: assetType,
    realized_gains_only: realizedGainsOnly,
  })
  return request(`/transactions/equity?${p}`)
}

export function sendCopilotMessage(messages) {
  return request('/copilot/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })
}

export function getAllocations(startDate, endDate, realizedGainsOnly) {
  const p = new URLSearchParams({
    stock_ticker: '',
    start_date: startDate,
    end_date: endDate,
    contract_type: 'ALL',
    realized_gains_only: realizedGainsOnly,
  })
  return request(`/transactions/options?${p}`)
}
