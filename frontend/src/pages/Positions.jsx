import { useState, useEffect } from 'react'
import { getPositions } from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

export default function Positions() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getPositions()
      .then(setData)
      .catch(() => setError('Failed to load positions. Make sure the API server is running.'))
      .finally(() => setLoading(false))
  }, [])

  const puts = data?.puts ?? []
  const calls = data?.calls ?? []
  const balances = data?.balances ?? null
  const stocks = data?.stocks ?? []

  const totalPutExposure = puts.reduce((sum, p) => sum + (p.exposure ?? 0), 0)
  const totalPutValue = puts.reduce((sum, p) => sum + (p.total_value ?? 0), 0)
  const totalCallValue = calls.reduce((sum, c) => sum + (c.total_value ?? 0), 0)

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">Positions</h2>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <Spinner />}

      {data && !loading && (
        <>
          {/* Balances */}
          {balances && (
            <div className="metrics-row">
              {balances.margin != null && (
                <div className="metric">
                  <span className="metric-label">Margin Balance</span>
                  <span className="metric-value">
                    ${balances.margin.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </span>
                </div>
              )}
              {balances.mutualFundValue != null && (
                <div className="metric">
                  <span className="metric-label">Mutual Fund</span>
                  <span className="metric-value">
                    ${balances.mutualFundValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </span>
                </div>
              )}
              {balances.account != null && (
                <div className="metric">
                  <span className="metric-label">Account Value</span>
                  <span className="metric-value highlight">
                    ${balances.account.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Stocks */}
          {stocks.length > 0 ? (
            <div className="card">
              <h3 className="section-title">Stocks</h3>
              <DataTable data={stocks} defaultSortKey="symbol" />
            </div>
          ) : (
            <div className="alert warning">No stocks found.</div>
          )}

          {/* Puts */}
          {puts.length > 0 ? (
            <div className="card">
              <h3 className="section-title">Puts</h3>
              <p className="summary-line">
                Total: {puts.length}&nbsp;&nbsp;|&nbsp;&nbsp;
                Exposure: ${totalPutExposure.toLocaleString('en-US', { minimumFractionDigits: 2 })}&nbsp;&nbsp;|&nbsp;&nbsp;
                Value: ${totalPutValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </p>
              <DataTable data={puts} defaultSortKey="expiration_date" />
            </div>
          ) : (
            <div className="alert warning">No PUT option positions found.</div>
          )}

          {/* Calls */}
          {calls.length > 0 ? (
            <div className="card">
              <h3 className="section-title">Calls</h3>
              <p className="summary-line">
                Total: {calls.length}&nbsp;&nbsp;|&nbsp;&nbsp;
                Value: ${totalCallValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </p>
              <DataTable data={calls} defaultSortKey="expiration_date" />
            </div>
          ) : (
            <div className="alert warning">No CALL option positions found.</div>
          )}
        </>
      )}
    </div>
  )
}
