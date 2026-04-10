import { useState, useEffect } from 'react'
import { getPositions } from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

const OPTION_COLUMNS = [
  { key: 'ticker',          label: 'Ticker' },
  { key: 'strike_price',    label: 'Strike' },
  { key: 'days_to_expiry',  label: 'DTE',         align: 'right' },
  { key: 'quantity',        label: 'Quantity',     align: 'right' },
  { key: 'trade_price',     label: 'Trade Price',  align: 'right' },
  { key: 'current_price',   label: 'Current Price',  align: 'right' },
  { key: 'total_value',     label: 'Total Value',  align: 'right' },
  { key: 'exposure',        label: 'Exposure',     align: 'right' },
  { key: 'symbol',          label: 'Symbol' },
]

export default function Positions() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getPositions()
      .then(setData)
      .catch((err) => {
        const msg = err?.message ?? ''
        if (msg.toLowerCase().includes('token') || msg.toLowerCase().includes('auth')) {
          setError('Broker authentication failed — the Schwab refresh token has expired. Please re-authenticate.')
        } else {
          setError('Failed to load positions. Make sure the API server is running.')
        }
      })
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
              {balances.cash_balance != null && (
                <div className="metric">
                  <span className="metric-label">Cash Balance</span>
                  <span className="metric-value">
                    ${balances.cash_balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}
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
              <DataTable data={puts} columns={OPTION_COLUMNS} defaultSortKey="days_to_expiry" />
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
              <DataTable data={calls} columns={OPTION_COLUMNS} defaultSortKey="days_to_expiry" />
            </div>
          ) : (
            <div className="alert warning">No CALL option positions found.</div>
          )}
        </>
      )}
    </div>
  )
}
