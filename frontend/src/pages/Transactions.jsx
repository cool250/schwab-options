import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getOptionTransactions, getEquityTransactions } from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

const OPTION_COLUMNS = [
  { key: 'symbol',          label: 'Symbol' },
  { key: 'close_date',    label: 'Closed Date' },
  { key: 'expirationDate', label: 'Expiry Date' },
  { key: 'open_type',     label: 'Opened As' },
  { key: 'amount',        label: 'Quantity',     align: 'right' },
  { key: 'close_price',   label: 'Closing Price',  align: 'right' },
  { key: 'open_price',     label: 'Opening Price',  align: 'right' },
  { key: 'total_amount',     label: 'Total',  align: 'right' },
  { key: 'option_type',     label: 'Option Type' },
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

export default function Transactions() {
  const [searchParams] = useSearchParams()
  const initialTab = searchParams.get('tab') === 'equity' ? 'equity' : 'options'
  const [tab, setTab] = useState(initialTab) // 'options' | 'equity'

  // ---- Option transactions ----
  const [ticker, setTicker] = useState(initialTab === 'options' ? (searchParams.get('ticker')?.toUpperCase() ?? '') : '')
  const [contractType, setContractType] = useState('ALL')
  const [realizedOnly, setRealizedOnly] = useState(initialTab === 'options' ? searchParams.get('realized') !== 'false' : true)
  const [startDate, setStartDate] = useState(() => (initialTab === 'options' ? (searchParams.get('start') ?? firstOfMonth()) : firstOfMonth()))
  const [endDate, setEndDate] = useState(() => (initialTab === 'options' ? (searchParams.get('end') ?? todayStr()) : todayStr()))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [transactions, setTransactions] = useState(null)

  async function runSearch(tickerVal, startVal, endVal, contractTypeVal, realizedVal) {
    setLoading(true)
    setError(null)
    setTransactions(null)
    try {
      const data = await getOptionTransactions(tickerVal.trim().toUpperCase(), startVal, endVal, contractTypeVal, realizedVal)
      setTransactions(data)
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
    runSearch(ticker, startDate, endDate, contractType, realizedOnly)
  }

  // Arriving from a chart click (e.g. Profit/Loss) pre-fills the filters via
  // the URL — run the search immediately instead of waiting for another click.
  useEffect(() => {
    if (initialTab === 'options' && (searchParams.get('ticker') || searchParams.get('start'))) {
      runSearch(ticker, startDate, endDate, contractType, realizedOnly)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const totalAmount = transactions?.reduce((s, t) => s + (t.total_amount ?? 0), 0) ?? 0

  // ---- Equity / futures transactions ----
  const [equityTicker, setEquityTicker] = useState(initialTab === 'equity' ? (searchParams.get('ticker')?.toUpperCase() ?? '') : '')
  const [assetType, setAssetType] = useState('ALL')
  const [equityRealizedOnly, setEquityRealizedOnly] = useState(initialTab === 'equity' ? searchParams.get('realized') !== 'false' : true)
  const [equityStartDate, setEquityStartDate] = useState(() => (initialTab === 'equity' ? (searchParams.get('start') ?? firstOfMonth()) : firstOfMonth()))
  const [equityEndDate, setEquityEndDate] = useState(() => (initialTab === 'equity' ? (searchParams.get('end') ?? todayStr()) : todayStr()))
  const [equityLoading, setEquityLoading] = useState(false)
  const [equityError, setEquityError] = useState(null)
  const [equityTransactions, setEquityTransactions] = useState(null)

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
    if (initialTab === 'equity' && (searchParams.get('ticker') || searchParams.get('start'))) {
      runEquitySearch(equityTicker, equityStartDate, equityEndDate, assetType, equityRealizedOnly)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const equityTotalAmount = equityTransactions?.reduce((s, t) => s + (t.total_amount ?? 0), 0) ?? 0

  return (
    <div className="page">
      <h2 className="page-title">Transactions</h2>

      <div className="button-row">
        <button
          type="button"
          className={`btn ${tab === 'options' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('options')}
        >
          Options
        </button>
        <button
          type="button"
          className={`btn ${tab === 'equity' ? 'btn-primary' : 'btn-secondary'}`}
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
                    onChange={(e) => setRealizedOnly(e.target.checked)}
                    className="toggle-checkbox"
                  />
                  <span>Realized Gains Only</span>
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
                    </span>
                  </div>
                  <DataTable data={transactions} columns={OPTION_COLUMNS} defaultSortKey="close_date" defaultSortDir="desc" />
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
              {equityTransactions.length === 0 ? (
                <div className="alert warning">No transactions found for the given criteria.</div>
              ) : (
                <div className="card">
                  <div className="section-header">
                    <h3 className="section-title">Transactions</h3>
                    <span className="summary-line">
                      {equityTransactions.length} records &nbsp;|&nbsp; Total: ${equityTotalAmount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <DataTable data={equityTransactions} columns={EQUITY_COLUMNS} defaultSortKey="close_date" defaultSortDir="desc" />
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
