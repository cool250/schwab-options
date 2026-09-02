import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getOptionTransactions, getOptionQuotes, getEquityTransactions } from '../api/client'
import { getMultiplier } from '../utils/contractMultiplier'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

const OPTION_COLUMNS = [
  { key: 'symbol',          label: 'Symbol' },
  { key: 'option_type',     label: 'Option Type' },
  { key: 'date',          label: 'Open' },
  { key: 'close_date',    label: 'Close' },
  { key: 'expirationDate', label: 'Expire' },
  { key: 'open_type',     label: 'Opened As' },
  { key: 'amount',        label: 'Qty',     align: 'right' },
  { key: 'open_price',     label: 'Open Price',  align: 'right' },
  { key: 'close_price',   label: 'Close Price',  align: 'right' },
  { key: 'total_amount',     label: 'Total',  align: 'right' },
  { key: 'type',     label: 'Status' },
]

const EQUITY_COLUMNS = [
  { key: 'symbol',       label: 'Symbol' },
  { key: 'date',         label: 'Opened' },
  { key: 'close_date',   label: 'Closed' },
  { key: 'asset_type',   label: 'Asset Type' },
  { key: 'quantity',     label: 'Quantity',    align: 'right' },
  { key: 'open_price',   label: 'Open Price',  align: 'right' },
  { key: 'close_price',  label: 'Close Price', align: 'right' },
  { key: 'total_amount', label: 'Total',       align: 'right' },
  { key: 'status',       label: 'Status' },
]

function firstOfMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

function todayStr() {
  return new Date().toISOString().split('T')[0]
}

// Survives unmounting/remounting this page (e.g. navigating to Reports and
// back) within the same browser session — only a full page reload or an
// explicit new search clears it. Without this, switching tabs away and back
// silently re-ran the last search and threw away whatever the user was
// looking at.
const transactionsCache = {
  tab: null,
  options: null, // { ticker, contractType, realizedOnly, unrealizedOnly, startDate, endDate, transactions, optionQuotes }
  equity: null, // { ticker, assetType, realizedOnly, startDate, endDate, transactions }
}

export default function Transactions() {
  const [searchParams] = useSearchParams()
  // A chart-click link (e.g. from Reports) always carries its own ticker/dates
  // and should run a fresh search rather than restoring whatever was cached.
  const fromLink = Boolean(searchParams.get('ticker') || searchParams.get('start'))
  const urlTab = searchParams.get('tab') === 'equity' ? 'equity' : (searchParams.get('tab') === 'options' ? 'options' : null)
  // An incoming link with no explicit ?tab= (the options-chart click-through)
  // means "options" specifically, not whatever tab happened to be cached —
  // only a plain revisit (no link params at all) should restore the cache.
  const initialTab = urlTab ?? (fromLink ? 'options' : transactionsCache.tab ?? 'options')
  const [tab, setTab] = useState(initialTab) // 'options' | 'equity'

  const cachedOptions = !fromLink ? transactionsCache.options : null
  const cachedEquity = !fromLink ? transactionsCache.equity : null

  // ---- Option transactions ----
  const [ticker, setTicker] = useState(
    initialTab === 'options' ? (searchParams.get('ticker')?.toUpperCase() ?? cachedOptions?.ticker ?? '') : ''
  )
  const [contractType, setContractType] = useState(cachedOptions?.contractType ?? 'ALL')
  const [realizedOnly, setRealizedOnly] = useState(
    initialTab === 'options' && searchParams.get('realized') ? searchParams.get('realized') !== 'false' : cachedOptions?.realizedOnly ?? true
  )
  const [unrealizedOnly, setUnrealizedOnly] = useState(
    initialTab === 'options' && searchParams.get('unrealized') ? searchParams.get('unrealized') === 'true' : cachedOptions?.unrealizedOnly ?? false
  )
  const [startDate, setStartDate] = useState(() => (
    initialTab === 'options' ? (searchParams.get('start') ?? cachedOptions?.startDate ?? firstOfMonth()) : (cachedOptions?.startDate ?? firstOfMonth())
  ))
  const [endDate, setEndDate] = useState(() => (
    initialTab === 'options' ? (searchParams.get('end') ?? cachedOptions?.endDate ?? todayStr()) : (cachedOptions?.endDate ?? todayStr())
  ))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [transactions, setTransactions] = useState(cachedOptions?.transactions ?? null)
  const [optionQuotes, setOptionQuotes] = useState(cachedOptions?.optionQuotes ?? {})
  const [optionQuotesLoading, setOptionQuotesLoading] = useState(false)

  useEffect(() => {
    transactionsCache.tab = tab
  }, [tab])

  useEffect(() => {
    transactionsCache.options = { ticker, contractType, realizedOnly, unrealizedOnly, startDate, endDate, transactions, optionQuotes }
  }, [ticker, contractType, realizedOnly, unrealizedOnly, startDate, endDate, transactions, optionQuotes])

  async function runSearch(tickerVal, startVal, endVal, contractTypeVal, realizedVal, unrealizedVal) {
    setLoading(true)
    setError(null)
    setTransactions(null)
    setOptionQuotes({})
    try {
      const tickerUpper = tickerVal.trim().toUpperCase()
      const data = await getOptionTransactions(tickerUpper, startVal, endVal, contractTypeVal, realizedVal, unrealizedVal)
      setTransactions(data)

      // Current price for still-open (unrealized) rows comes from Tastytrade
      // (Schwab has no quote endpoint we can use here either) — fetched
      // separately so the table itself renders immediately instead of
      // blocking on it. Needed whenever open rows can appear in the result:
      // either the unrealized-only view, or the unfiltered "show everything"
      // view (realizedVal false, unrealizedVal false) which mixes open and
      // closed rows together. Realized-only never has open rows, so skip it.
      if (!realizedVal && data.length > 0) {
        setOptionQuotesLoading(true)
        getOptionQuotes(tickerUpper, startVal, endVal, contractTypeVal)
          .then(setOptionQuotes)
          .catch(() => {})
          .finally(() => setOptionQuotesLoading(false))
      }
    } catch (err) {
      const msg = err?.message ?? ''
      if (msg.toLowerCase().includes('token') || msg.toLowerCase().includes('auth')) {
        setError('Broker authentication failed — the Schwab refresh token has expired. Please re-authenticate.')
      } else {
        setError('Failed to fetch transactions. Make sure the API server is running.')
      }
    } finally {
      setLoading(false)
    }
  }

  function handleSearch(e) {
    e.preventDefault()
    runSearch(ticker, startDate, endDate, contractType, realizedOnly, unrealizedOnly)
  }

  // Arriving from a chart click (e.g. Reports) pre-fills the filters via the
  // URL — run the search immediately instead of waiting for another click.
  // Otherwise (a plain revisit of this page), the cached results restored
  // above are shown as-is with no fetch at all.
  useEffect(() => {
    if (initialTab === 'options' && fromLink) {
      runSearch(ticker, startDate, endDate, contractType, realizedOnly, unrealizedOnly)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Total is a realized gain/loss figure — a still-open leg's total_amount is
  // just its entry credit/debit, not a completed gain, so zero it here (its
  // unrealized gain is shown separately via the Unrealized Gain column).
  const optionRows = (transactions ?? []).map((t) => (t.type === 'TRADE' ? { ...t, total_amount: 0 } : t))
  const totalAmount = optionRows.reduce((s, t) => s + (t.total_amount ?? 0), 0)

  // Unrealized gain isn't a field on the row — it depends on the live price
  // fetched separately above — so it's added as a render-only column (like
  // the futures tab's current_price) rather than merged into the row data.
  function currentPriceColumn() {
    return {
      key: 'current_price',
      label: 'Current Price',
      align: 'right',
      render: (row) => {
        const price = optionQuotes[row.symbol]
        if (price != null) return `$${price.toFixed(2)}`
        return optionQuotesLoading ? '…' : '—'
      },
    }
  }

  function unrealizedGainColumn() {
    return {
      key: 'unrealized_gain',
      label: 'Unrealized Gain',
      align: 'right',
      render: (row) => {
        const price = optionQuotes[row.symbol]
        if (price == null) return optionQuotesLoading ? '…' : '—'
        const gain = row.amount * getMultiplier(row.underlying_symbol) * (price - row.open_price)
        const cls = gain > 0 ? 'cell-positive' : gain < 0 ? 'cell-negative' : ''
        return (
          <span className={cls}>
            ${gain.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        )
      },
    }
  }

  // Live pricing/unrealized-gain columns are relevant whenever open rows can
  // appear: the unrealized-only view (every row is open), or the unfiltered
  // "show everything" view (open and closed rows mixed). Realized-only never
  // has open rows. Close Price is only dropped in the pure-unrealized view —
  // in the mixed view, closed rows still have a real close price to show.
  const showLivePricing = !realizedOnly
  const optionColumns = showLivePricing
    ? [
        ...(unrealizedOnly ? OPTION_COLUMNS.filter((c) => c.key !== 'close_price') : OPTION_COLUMNS),
        currentPriceColumn(),
        unrealizedGainColumn(),
      ]
    : OPTION_COLUMNS

  const totalUnrealizedGain = showLivePricing
    ? (transactions ?? []).reduce((s, t) => {
        const price = optionQuotes[t.symbol]
        return price == null ? s : s + t.amount * getMultiplier(t.underlying_symbol) * (price - t.open_price)
      }, 0)
    : null

  // ---- Equity / futures transactions ----
  const [equityTicker, setEquityTicker] = useState(
    initialTab === 'equity' ? (searchParams.get('ticker')?.toUpperCase() ?? cachedEquity?.ticker ?? '') : ''
  )
  const [assetType, setAssetType] = useState(cachedEquity?.assetType ?? 'ALL')
  const [equityRealizedOnly, setEquityRealizedOnly] = useState(
    initialTab === 'equity' && searchParams.get('realized') ? searchParams.get('realized') !== 'false' : cachedEquity?.realizedOnly ?? true
  )
  const [equityStartDate, setEquityStartDate] = useState(() => (
    initialTab === 'equity' ? (searchParams.get('start') ?? cachedEquity?.startDate ?? firstOfMonth()) : (cachedEquity?.startDate ?? firstOfMonth())
  ))
  const [equityEndDate, setEquityEndDate] = useState(() => (
    initialTab === 'equity' ? (searchParams.get('end') ?? cachedEquity?.endDate ?? todayStr()) : (cachedEquity?.endDate ?? todayStr())
  ))
  const [equityLoading, setEquityLoading] = useState(false)
  const [equityError, setEquityError] = useState(null)
  const [equityTransactions, setEquityTransactions] = useState(cachedEquity?.transactions ?? null)

  useEffect(() => {
    transactionsCache.equity = {
      ticker: equityTicker, assetType, realizedOnly: equityRealizedOnly,
      startDate: equityStartDate, endDate: equityEndDate, transactions: equityTransactions,
    }
  }, [equityTicker, assetType, equityRealizedOnly, equityStartDate, equityEndDate, equityTransactions])

  async function runEquitySearch(tickerVal, startVal, endVal, assetTypeVal, realizedVal) {
    setEquityLoading(true)
    setEquityError(null)
    setEquityTransactions(null)
    try {
      const data = await getEquityTransactions(tickerVal.trim().toUpperCase(), startVal, endVal, assetTypeVal, realizedVal)
      setEquityTransactions(data)
    } catch (err) {
      const msg = err?.message ?? ''
      if (msg.toLowerCase().includes('token') || msg.toLowerCase().includes('auth')) {
        setEquityError('Broker authentication failed — the Schwab refresh token has expired. Please re-authenticate.')
      } else {
        setEquityError('Failed to fetch transactions. Make sure the API server is running.')
      }
    } finally {
      setEquityLoading(false)
    }
  }

  function handleEquitySearch(e) {
    e.preventDefault()
    runEquitySearch(equityTicker, equityStartDate, equityEndDate, assetType, equityRealizedOnly)
  }

  // Mirrors the options-tab bootstrap above, for links that arrive with ?tab=equity.
  useEffect(() => {
    if (initialTab === 'equity' && fromLink) {
      runEquitySearch(equityTicker, equityStartDate, equityEndDate, assetType, equityRealizedOnly)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // This account never opens an outright equity/futures short — a negative
  // signed quantity on an otherwise-"OPEN" row means the matcher found a
  // closing trade but never saw its opening fill (outside the lookback
  // window), not that a new short was opened. The date/price we do have
  // belong to that closing trade, not an opening leg, so show them as
  // Closed/Close Price instead of Opened/Open Price — the true open leg is
  // simply unknown, not present.
  //
  // Either way — an unmatched open (no close yet) or an unmatched close (no
  // open on record) — there's no way to compute a real gain/loss without
  // both legs, so Total shows 0 until a full round-trip is on record.
  const equityRows = (equityTransactions ?? []).map((t) => {
    if (t.quantity < 0) {
      return {
        ...t,
        close_date: t.date,
        close_price: t.open_price,
        date: null,
        open_price: null,
        status: 'CLOSED',
        total_amount: 0,
      }
    }
    return t.close_price == null ? { ...t, total_amount: 0 } : t
  })
  const equityTotalAmount = equityRows.reduce((s, t) => s + (t.total_amount ?? 0), 0)

  return (
    <div className="page">
      <h2 className="page-title">Transactions</h2>

      <div className="tab-row">
        <button
          type="button"
          className={`tab-item ${tab === 'options' ? 'active' : ''}`}
          onClick={() => setTab('options')}
        >
          Options
        </button>
        <button
          type="button"
          className={`tab-item ${tab === 'equity' ? 'active' : ''}`}
          onClick={() => setTab('equity')}
        >
          Equity &amp; Futures
        </button>
      </div>

      {tab === 'options' ? (
        <>
          <div className="card">
            <form onSubmit={handleSearch}>
              <div className="form-row">
                <div className="form-group">
                  <label>Ticker Symbol</label>
                  <input
                    type="text"
                    value={ticker}
                    onChange={(e) => setTicker(e.target.value.toUpperCase())}
                    placeholder="e.g. AAPL (blank = all)"
                    className="input"
                  />
                </div>
                <div className="form-group">
                  <label>Option Type</label>
                  <select value={contractType} onChange={(e) => setContractType(e.target.value)} className="input">
                    <option value="ALL">ALL</option>
                    <option value="PUT">PUT</option>
                    <option value="CALL">CALL</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>From Date</label>
                  <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="input" />
                </div>
                <div className="form-group">
                  <label>To Date</label>
                  <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="input" />
                </div>
              </div>

              <div className="form-actions">
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={realizedOnly}
                    onChange={(e) => {
                      const checked = e.target.checked
                      setRealizedOnly(checked)
                      if (checked) setUnrealizedOnly(false)
                    }}
                    className="toggle-checkbox"
                  />
                  <span>Realized Gains Only</span>
                </label>
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={unrealizedOnly}
                    onChange={(e) => {
                      const checked = e.target.checked
                      setUnrealizedOnly(checked)
                      if (checked) setRealizedOnly(false)
                    }}
                    className="toggle-checkbox"
                  />
                  <span>Unrealized Gains Only</span>
                </label>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  Search Transactions
                </button>
              </div>
            </form>
          </div>

          {error && <div className="alert error">{error}</div>}
          {loading && <Spinner />}

          {transactions && !loading && (
            <>
              {transactions.length === 0 ? (
                <div className="alert warning">No transactions found for the given criteria.</div>
              ) : (
                <div className="card">
                  <div className="section-header">
                    <h3 className="section-title">Transactions</h3>
                    <span className="summary-line">
                      {transactions.length} records &nbsp;|&nbsp; Total: ${totalAmount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                      {showLivePricing && (
                        <>
                          &nbsp;|&nbsp; Unrealized Gain: ${totalUnrealizedGain.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </>
                      )}
                    </span>
                  </div>
                  <DataTable data={optionRows} columns={optionColumns} defaultSortKey="close_date" defaultSortDir="desc" />
                </div>
              )}
            </>
          )}
        </>
      ) : (
        <>
          <div className="card">
            <form onSubmit={handleEquitySearch}>
              <div className="form-row">
                <div className="form-group">
                  <label>Ticker / Futures Root</label>
                  <input
                    type="text"
                    value={equityTicker}
                    onChange={(e) => setEquityTicker(e.target.value.toUpperCase())}
                    placeholder="e.g. AAPL, ES (blank = all)"
                    className="input"
                  />
                </div>
                <div className="form-group">
                  <label>Asset Type</label>
                  <select value={assetType} onChange={(e) => setAssetType(e.target.value)} className="input">
                    <option value="ALL">ALL</option>
                    <option value="EQUITY">EQUITY</option>
                    <option value="FUTURE">FUTURE</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>From Date</label>
                  <input type="date" value={equityStartDate} onChange={(e) => setEquityStartDate(e.target.value)} className="input" />
                </div>
                <div className="form-group">
                  <label>To Date</label>
                  <input type="date" value={equityEndDate} onChange={(e) => setEquityEndDate(e.target.value)} className="input" />
                </div>
              </div>

              <div className="form-actions">
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={equityRealizedOnly}
                    onChange={(e) => setEquityRealizedOnly(e.target.checked)}
                    className="toggle-checkbox"
                  />
                  <span>Realized Gains Only</span>
                </label>
                <button type="submit" className="btn btn-primary" disabled={equityLoading}>
                  Search Transactions
                </button>
              </div>
            </form>
          </div>

          {equityError && <div className="alert error">{equityError}</div>}
          {equityLoading && <Spinner />}

          {equityTransactions && !equityLoading && (
            <>
              {equityRows.length === 0 ? (
                <div className="alert warning">No transactions found for the given criteria.</div>
              ) : (
                <div className="card">
                  <div className="section-header">
                    <h3 className="section-title">Transactions</h3>
                    <span className="summary-line">
                      {equityRows.length} records &nbsp;|&nbsp; Total: ${equityTotalAmount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <DataTable data={equityRows} columns={EQUITY_COLUMNS} defaultSortKey="close_date" defaultSortDir="desc" />
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
