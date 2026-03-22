import { useState } from 'react'
import { getTickerPrice, getMaxReturn, getAllExpirations } from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

function todayStr() {
  return new Date().toISOString().split('T')[0]
}

function in8DaysStr() {
  const d = new Date()
  d.setDate(d.getDate() + 8)
  return d.toISOString().split('T')[0]
}

export default function MarketData() {
  const [ticker, setTicker] = useState('')
  const [currentPrice, setCurrentPrice] = useState(null)
  const [priceStatus, setPriceStatus] = useState(null) // 'ok' | 'err' | null
  const [lastFetchedTicker, setLastFetchedTicker] = useState('')
  const [strikePrice, setStrikePrice] = useState('')
  const [optionType, setOptionType] = useState('PUT')
  const [fromDate, setFromDate] = useState(todayStr)
  const [toDate, setToDate] = useState(in8DaysStr)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState(null) // 'expirations' | 'maxReturn'
  const [results, setResults] = useState(null)

  async function handleTickerBlur() {
    const t = ticker.trim().toUpperCase()
    if (!t) { setCurrentPrice(null); setPriceStatus(null); setLastFetchedTicker(''); return }
    if (t === lastFetchedTicker) return   // same ticker, nothing to do
    try {
      const data = await getTickerPrice(t)
      setCurrentPrice(data.price)
      setPriceStatus('ok')
      setLastFetchedTicker(t)
      setStrikePrice(String(Math.round(data.price)))
    } catch {
      setCurrentPrice(null)
      setPriceStatus('err')
    }
  }

  function validate() {
    if (!ticker.trim()) { setError('Please enter a ticker symbol.'); return false }
    if (!strikePrice || parseFloat(strikePrice) <= 0) { setError('Please enter a valid strike price.'); return false }
    setError(null)
    return true
  }

  async function handleMaxReturn() {
    if (!validate()) return
    setLoading(true); setResults(null); setMode('maxReturn')
    try {
      const data = await getMaxReturn(ticker.trim().toUpperCase(), parseFloat(strikePrice), fromDate, toDate, optionType)
      setResults(data)
    } catch {
      setError('Failed to fetch max return data.')
    } finally {
      setLoading(false)
    }
  }

  async function handleExpirations() {
    if (!validate()) return
    setLoading(true); setResults(null); setMode('expirations')
    try {
      const data = await getAllExpirations(ticker.trim().toUpperCase(), parseFloat(strikePrice), fromDate, toDate, optionType)
      setResults(data)
    } catch {
      setError('Failed to fetch expiration data.')
    } finally {
      setLoading(false)
    }
  }

  const sym = ticker.trim().toUpperCase()

  return (
    <div className="page">
      <h2 className="page-title">Options Chain Analyzer</h2>

      <div className="card">
        {/* Ticker — outside the grid so price hint appears beneath it */}
        <div className="form-group form-group--sm">
          <label>Ticker Symbol</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onBlur={handleTickerBlur}
            placeholder="e.g. AAPL"
            className="input"
          />
          {sym && priceStatus === 'ok' && currentPrice !== null && (
            <span className="price-badge ok">
              Current price for <strong>{sym}</strong>: ${currentPrice.toFixed(2)}
            </span>
          )}
          {sym && priceStatus === 'err' && (
            <span className="price-badge err">Could not fetch price for {sym}.</span>
          )}
        </div>

        <div className="form-row">
          <div className="form-group">
            <label>Strike Price</label>
            <input
              type="number"
              value={strikePrice}
              onChange={(e) => setStrikePrice(e.target.value)}
              placeholder="e.g. 200"
              className="input"
              min="0"
            />
          </div>
          <div className="form-group">
            <label>Option Type</label>
            <select value={optionType} onChange={(e) => setOptionType(e.target.value)} className="input">
              <option value="PUT">PUT</option>
              <option value="CALL">CALL</option>
            </select>
          </div>
          <div className="form-group">
            <label>From Date</label>
            <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} className="input" />
          </div>
          <div className="form-group">
            <label>To Date</label>
            <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} className="input" />
          </div>
        </div>

        <div className="button-row">
          <button onClick={handleExpirations} className="btn btn-secondary" disabled={loading}>
            Expiration Dates
          </button>
          <button onClick={handleMaxReturn} className="btn btn-primary" disabled={loading}>
            Max Return
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <Spinner />}

      {/* Max Return result */}
      {!loading && results && mode === 'maxReturn' && (
        <div className="card">
          <h3 className="section-title">Max Return — {sym}</h3>
          {results.message ? (
            <p className="text-muted">{results.message}</p>
          ) : (
            <div className="result-metrics">
              <div className="metric">
                <span className="metric-label">Best Expiration</span>
                <span className="metric-value">{results.expiration_date}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Max Annualized Return</span>
                <span className="metric-value highlight">{results.annualized_return?.toFixed(2)}%</span>
              </div>
              <div className="metric">
                <span className="metric-label">Option Price</span>
                <span className="metric-value">${results.price?.toFixed(2)}</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Expirations table */}
      {!loading && results && mode === 'expirations' && Array.isArray(results) && (
        <div className="card">
          <h3 className="section-title">
            {optionType} returns for {sym}
            {priceStatus === 'ok' && currentPrice !== null ? ` @ $${currentPrice.toFixed(2)}` : ''}
          </h3>
          {results.length === 0 ? (
            <p className="text-muted">No data found for the given inputs.</p>
          ) : (
            <DataTable
              data={results}
              columns={[
                { key: 'expiration_date', label: 'Expiration Date' },
                { key: 'strike', label: 'Strike ($)' },
                { key: 'price', label: 'Price ($)' },
                { key: 'annualized_return', label: 'Annualized Return (%)' },
              ]}
              defaultSortKey="expiration_date"
            />
          )}
        </div>
      )}
    </div>
  )
}
