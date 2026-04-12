import { useState } from 'react'
import { getOptionTransactions } from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

const COLUMNS = [
  { key: 'symbol',          label: 'Symbol' },
  { key: 'close_date',    label: 'Closed Date' },
  { key: 'amount',        label: 'Quantity',     align: 'right' },
  { key: 'close_price',   label: 'Closing Price',  align: 'right' },
  { key: 'open_price',     label: 'Opening Price',  align: 'right' },
  { key: 'total_amount',     label: 'Total',  align: 'right' },
  { key: 'option_type',     label: 'Option Type' },
  { key: 'type',     label: 'Status' },
]

function firstOfMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

function todayStr() {
  return new Date().toISOString().split('T')[0]
}

export default function Transactions() {
  const [ticker, setTicker] = useState('')
  const [contractType, setContractType] = useState('ALL')
  const [realizedOnly, setRealizedOnly] = useState(true)
  const [startDate, setStartDate] = useState(firstOfMonth)
  const [endDate, setEndDate] = useState(todayStr)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [transactions, setTransactions] = useState(null)

  async function handleSearch(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setTransactions(null)
    try {
      const data = await getOptionTransactions(ticker.trim().toUpperCase(), startDate, endDate, contractType, realizedOnly)
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

  const totalAmount = transactions?.reduce((s, t) => s + (t.total_amount ?? 0), 0) ?? 0

  return (
    <div className="page">
      <h2 className="page-title">Option Transactions</h2>

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
              <DataTable data={transactions} columns={COLUMNS} defaultSortKey="close_date" defaultSortDir="desc" />
            </div>
          )}
        </>
      )}
    </div>
  )
}
