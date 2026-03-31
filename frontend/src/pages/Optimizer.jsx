import { useState, useCallback } from 'react'
import { getOptimizerRecs } from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

const CALL_COLUMNS = [
  { key: 'symbol',            label: 'Ticker' },
  { key: 'strike',            label: 'Strike',        align: 'right' },
  { key: 'expiration_date',   label: 'Expiry',        align: 'right' },
  { key: 'dte',               label: 'DTE',           align: 'right' },
  { key: 'premium',           label: 'Premium',       align: 'right' },
  { key: 'annualized_return', label: 'Ann. Return %', align: 'right' },
  { key: 'contracts',         label: 'Contracts',     align: 'right' },
  { key: 'margin_required',   label: 'Collateral',    align: 'right' },
  { key: 'delta',             label: 'Delta',         align: 'right' },
]

const PUT_COLUMNS = [
  { key: 'symbol',            label: 'Ticker' },
  { key: 'strike',            label: 'Strike',        align: 'right' },
  { key: 'expiration_date',   label: 'Expiry',        align: 'right' },
  { key: 'dte',               label: 'DTE',           align: 'right' },
  { key: 'premium',           label: 'Premium',       align: 'right' },
  { key: 'annualized_return', label: 'Ann. Return %', align: 'right' },
  { key: 'contracts',         label: 'Contracts',     align: 'right' },
  { key: 'margin_required',   label: 'Margin',        align: 'right' },
  { key: 'delta',             label: 'Delta',         align: 'right' },
]

export default function Optimizer() {
  const [extraSymbols, setExtraSymbols] = useState('')
  const [maxDte, setMaxDte] = useState(7)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const run = useCallback(() => {
    setLoading(true)
    setError(null)
    setData(null)
    getOptimizerRecs({ extraSymbols, maxDte })
      .then(setData)
      .catch((e) => setError(e.message || 'Failed to load recommendations.'))
      .finally(() => setLoading(false))
  }, [extraSymbols, maxDte])

  const calls = data?.calls ?? []
  const puts = data?.puts ?? []

  const totalCallPremium = calls.reduce((s, r) => s + (r.premium_total ?? 0), 0)
  const totalPutPremium = puts.reduce((s, r) => s + (r.premium_total ?? 0), 0)

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">Wheel Optimizer</h2>
      </div>

      {/* Controls */}
      <div className="card">
        <div className="form-row form-row--2">
          <div className="form-group">
            <label>Extra Tickers (Puts)</label>
            <input
              className="input"
              placeholder="e.g. SPY,QQQ"
              value={extraSymbols}
              onChange={(e) => setExtraSymbols(e.target.value.toUpperCase())}
            />
          </div>
          <div className="form-group">
            <label>Max DTE</label>
            <input
              className="input"
              type="number"
              min={1}
              max={60}
              value={maxDte}
              onChange={(e) => setMaxDte(Number(e.target.value))}
            />
          </div>
        </div>

        <div className="button-row">
          <button className="btn btn-primary" onClick={run} disabled={loading}>
            {loading ? 'Running…' : 'Run Optimizer'}
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <Spinner />}

      {data && !loading && (
        <>
          {/* Covered Calls */}
          <div className="card">
            <div className="section-header">
              <h3 className="section-title">Covered Calls</h3>
              {calls.length > 0 && (
                <span className="summary-line">
                  {calls.length} recommendation{calls.length !== 1 ? 's' : ''}&nbsp;&nbsp;|&nbsp;&nbsp;
                  Est. premium: ${totalCallPremium.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </span>
              )}
            </div>
            {calls.length > 0 ? (
              <DataTable data={calls} columns={CALL_COLUMNS} defaultSortKey="annualized_return" />
            ) : (
              <div className="alert warning">No covered call opportunities found.</div>
            )}
          </div>

          {/* Cash-Secured Puts */}
          <div className="card">
            <div className="section-header">
              <h3 className="section-title">Cash-Secured Puts</h3>
              {puts.length > 0 && (
                <span className="summary-line">
                  {puts.length} recommendation{puts.length !== 1 ? 's' : ''}&nbsp;&nbsp;|&nbsp;&nbsp;
                  Est. premium: ${totalPutPremium.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </span>
              )}
            </div>
            {puts.length > 0 ? (
              <DataTable data={puts} columns={PUT_COLUMNS} defaultSortKey="annualized_return" />
            ) : (
              <div className="alert warning">No cash-secured put opportunities found.</div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
