const BASE = '/api'

function getToken() {
  return sessionStorage.getItem('auth_token')
}

async function request(path) {
  const token = getToken()
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  const res = await fetch(`${BASE}${path}`, { headers })
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
    throw new Error(message)
  }
  return res.json()
}

export function getTickerPrice(symbol) {
  return request(`/market/price/${encodeURIComponent(symbol)}`)
}

export function getMaxReturn(symbol, strike, fromDate, toDate, contractType) {
  const p = new URLSearchParams({ symbol, strike, from_date: fromDate, to_date: toDate, contract_type: contractType })
  return request(`/market/options/best?${p}`)
}

export function getAllExpirations(symbol, strike, fromDate, toDate, contractType) {
  const p = new URLSearchParams({ symbol, strike, from_date: fromDate, to_date: toDate, contract_type: contractType })
  return request(`/market/options/expirations?${p}`)
}

export function getPositions() {
  return request('/positions/')
}

export function getOptionTransactions(stockTicker, startDate, endDate, contractType, realizedGainsOnly) {
  const p = new URLSearchParams({
    stock_ticker: stockTicker,
    start_date: startDate,
    end_date: endDate,
    contract_type: contractType,
    realized_gains_only: realizedGainsOnly,
  })
  return request(`/transactions/options?${p}`)
}

export function getOptimizerRecs({ extraSymbols = '', maxDte = 7 } = {}) {
  const p = new URLSearchParams({ max_dte: maxDte })
  if (extraSymbols) p.set('extra_symbols', extraSymbols)
  return request(`/optimizer/?${p}`)
}

export function getMonthlyAllocations(year, month, realizedGainsOnly) {
  const startDate = `${year}-${String(month).padStart(2, '0')}-01`
  const lastDay = new Date(year, month, 0).getDate()
  const endDate = `${year}-${String(month).padStart(2, '0')}-${lastDay}`
  const p = new URLSearchParams({
    stock_ticker: '',
    start_date: startDate,
    end_date: endDate,
    contract_type: 'ALL',
    realized_gains_only: realizedGainsOnly,
  })
  return request(`/transactions/options?${p}`)
}
