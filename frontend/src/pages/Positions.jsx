import { useState, useEffect } from 'react'
import { getPositions, getFuturesPosition, getFuturesOptionPosition } from '../api/client'
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

const FUTURES_COLUMNS = [
  { key: 'symbol',      label: 'Symbol' },
  { key: 'quantity',    label: 'Quantity',   align: 'right' },
  { key: 'open_price',  label: 'Open Price', align: 'right' },
  { key: 'cost_basis',  label: 'Cost Basis', align: 'right' },
]

const FUTURES_OPTION_COLUMNS = [
  { key: 'ticker',          label: 'Ticker' },
  { key: 'strike_price',    label: 'Strike' },
  { key: 'days_to_expiry',  label: 'DTE',         align: 'right' },
  { key: 'quantity',        label: 'Quantity',    align: 'right' },
  { key: 'trade_price',     label: 'Trade Price', align: 'right' },
  { key: 'current_price',   label: 'Current Price', align: 'right' },
  { key: 'symbol',          label: 'Symbol' },
]

export default function Positions() {
  const [tab, setTab] = useState('equity') // 'equity' | 'futures'
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Futures data is fetched lazily — the futures-option lookup goes through
  // Tastytrade's DXLink feed per open expiration (Schwab's quote endpoint
  // rejects futures-option symbols outright) and can take several seconds,
  // so it's only worth paying for once the user actually opens this tab.
  const [futuresData, setFuturesData] = useState(null)
  const [futuresLoading, setFuturesLoading] = useState(false)
  const [futuresError, setFuturesError] = useState(null)

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

  useEffect(() => {
    if (tab !== 'futures' || futuresData || futuresLoading) return
    setFuturesLoading(true)
    setFuturesError(null)
    Promise.all([getFuturesPosition(), getFuturesOptionPosition()])
      .then(([futures, futuresOptions]) => {
        setFuturesData({ futures, ...futuresOptions })
      })
      .catch((err) => {
        const msg = err?.message ?? ''
        if (msg.toLowerCase().includes('token') || msg.toLowerCase().includes('auth')) {
          setFuturesError('Broker authentication failed — the Schwab refresh token has expired. Please re-authenticate.')
        } else {
          setFuturesError('Failed to load futures positions. Make sure the API server is running.')
        }
      })
      .finally(() => setFuturesLoading(false))
  }, [tab, futuresData, futuresLoading])

  const puts = data?.puts ?? []
  const calls = data?.calls ?? []
  const balances = data?.balances ?? null
  const stocks = data?.stocks ?? []
  const futures = futuresData?.futures ?? []
  const futuresPuts = futuresData?.puts ?? []
  const futuresCalls = futuresData?.calls ?? []

  const totalPutExposure = puts.reduce((sum, p) => sum + (p.exposure ?? 0), 0)
  const totalPutValue = puts.reduce((sum, p) => sum + (p.total_value ?? 0), 0)
  const totalCallValue = calls.reduce((sum, c) => sum + (c.total_value ?? 0), 0)

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">Positions</h2>
      </div>

      <div className="button-row">
        <button
          type="button"
          className={`btn ${tab === 'equity' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('equity')}
        >
          Equity
        </button>
        <button
          type="button"
          className={`btn ${tab === 'futures' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('futures')}
        >
          Futures
        </button>
      </div>

      {tab === 'equity' && (
        <>
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
        </>
      )}

      {tab === 'futures' && (
        <>
          {futuresError && <div className="alert error">{futuresError}</div>}
          {futuresLoading && <Spinner />}

          {futuresData && !futuresLoading && (
            <>
              {/* Futures */}
              {futures.length > 0 ? (
                <div className="card">
                  <h3 className="section-title">Futures</h3>
                  <DataTable data={futures} columns={FUTURES_COLUMNS} defaultSortKey="symbol" />
                </div>
              ) : (
                <div className="alert warning">No open futures positions found.</div>
              )}

              {/* Futures Puts */}
              {futuresPuts.length > 0 ? (
                <div className="card">
                  <h3 className="section-title">Futures Puts</h3>
                  <DataTable data={futuresPuts} columns={FUTURES_OPTION_COLUMNS} defaultSortKey="days_to_expiry" />
                </div>
              ) : (
                <div className="alert warning">No open futures PUT positions found.</div>
              )}

              {/* Futures Calls */}
              {futuresCalls.length > 0 ? (
                <div className="card">
                  <h3 className="section-title">Futures Calls</h3>
                  <DataTable data={futuresCalls} columns={FUTURES_OPTION_COLUMNS} defaultSortKey="days_to_expiry" />
                </div>
              ) : (
                <div className="alert warning">No open futures CALL positions found.</div>
              )}

              <p className="text-muted">
                Derived from transaction history — Schwab's positions API doesn't report futures contracts or futures options directly, so this only looks back 30 days and may miss a position opened earlier than that.
              </p>
            </>
          )}
        </>
      )}
    </div>
  )
}
