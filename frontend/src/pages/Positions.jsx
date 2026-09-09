import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getPositions, getFuturesPosition, getFuturesOptionPosition, getFuturesOptionQuotes, friendlyErrorMessage } from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

// Position fields come back pre-formatted for display (e.g. "$1,234.56", "-2") —
// undo that so the value can be passed to StrikeLab as a real number.
function toNumber(value) {
  const n = Number(String(value ?? '').replace(/[$,]/g, ''))
  return Number.isFinite(n) ? n : 0
}

// Survives unmounting/remounting this page (e.g. navigating to Analyze and
// back) within the same browser session — only a full page reload clears it.
// Positions don't change fast enough to justify refetching (and, for futures
// options, re-paying the several-seconds DXLink quote lookup) on every visit.
const positionsCache = {
  data: null,
  futuresData: null,
  futuresQuotes: null,
}

const OPTION_COLUMNS = [
  { key: 'ticker',          label: 'Ticker' },
  { key: 'strike_price',    label: 'Strike' },
  { key: 'days_to_expiry',  label: 'DTE',         align: 'right' },
  { key: 'quantity',        label: 'Quantity',     align: 'right' },
  { key: 'trade_price',     label: 'Trade Price',  align: 'right' },
  { key: 'current_price',   label: 'Current Price',  align: 'right' },
  { key: 'total_value',     label: 'P&L',          align: 'right' },
  { key: 'exposure',        label: 'Exposure',     align: 'right' },
  { key: 'symbol',          label: 'Symbol' },
]

const FUTURES_COLUMNS = [
  { key: 'symbol',      label: 'Symbol' },
  { key: 'quantity',    label: 'Quantity',   align: 'right' },
  { key: 'open_price',  label: 'Open Price', align: 'right' },
  { key: 'cost_basis',  label: 'Cost Basis', align: 'right' },
]

// current_price isn't part of this — get_futures_option_position() doesn't
// return it (see the futuresQuotes lazy-load below), so it's added as its
// own render-based column instead of a plain key.
const FUTURES_OPTION_COLUMNS = [
  { key: 'ticker',          label: 'Ticker' },
  { key: 'symbol',          label: 'Symbol' },
  { key: 'strike_price',    label: 'Strike' },
  { key: 'days_to_expiry',  label: 'DTE',         align: 'right' },
  { key: 'quantity',        label: 'Quantity',    align: 'right' },
  { key: 'trade_price',     label: 'Trade Price', align: 'right' },
]


export default function Positions() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('equity') // 'equity' | 'futures'
  const [data, setData] = useState(positionsCache.data)
  const [loading, setLoading] = useState(!positionsCache.data)
  const [error, setError] = useState(null)

  // Futures data is fetched lazily — the futures-option lookup goes through
  // Tastytrade's DXLink feed per open expiration (Schwab's quote endpoint
  // rejects futures-option symbols outright) and can take several seconds,
  // so it's only worth paying for once the user actually opens this tab.
  const [futuresData, setFuturesData] = useState(positionsCache.futuresData)
  const [futuresLoading, setFuturesLoading] = useState(false)
  const [futuresError, setFuturesError] = useState(null)

  // current_price for futures options is fetched separately, after the
  // position list itself, so the table renders with everything except price
  // right away instead of blocking on the slow DXLink lookup. Keyed by symbol.
  const [futuresQuotes, setFuturesQuotes] = useState(positionsCache.futuresQuotes ?? {})
  const [futuresQuotesLoading, setFuturesQuotesLoading] = useState(false)

  // Options picked (across either tab) to send to StrikeLab — keyed by the
  // row's own symbol, since that's unique per contract.
  const [selected, setSelected] = useState(new Map())

  useEffect(() => {
    if (positionsCache.data) return
    getPositions()
      .then((d) => {
        positionsCache.data = d
        setData(d)
      })
      .catch((err) => {
        setError(friendlyErrorMessage(err, 'Failed to load positions. Make sure the API server is running.'))
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    // Deliberately excludes futuresLoading from the guard/deps: including it
    // turned every failure into an infinite retry loop (loading -> false ->
    // effect re-fires because futuresData is still null -> clears the error
    // -> fails again), so the error banner never stayed on screen long enough
    // to read. Re-fetching now only happens on an actual tab switch.
    if (tab !== 'futures' || futuresData) return
    setFuturesLoading(true)
    setFuturesError(null)
    Promise.all([getFuturesPosition(), getFuturesOptionPosition()])
      .then(([futures, futuresOptions]) => {
        const combined = { futures, ...futuresOptions }
        positionsCache.futuresData = combined
        setFuturesData(combined)
      })
      .catch((err) => {
        setFuturesError(friendlyErrorMessage(err, 'Failed to load futures positions. Make sure the API server is running.'))
      })
      .finally(() => setFuturesLoading(false))
  }, [tab, futuresData])

  useEffect(() => {
    if (!futuresData || positionsCache.futuresQuotes) return
    setFuturesQuotesLoading(true)
    getFuturesOptionQuotes()
      .then((quotes) => {
        positionsCache.futuresQuotes = quotes
        setFuturesQuotes(quotes)
      })
      // Prices are a nicety layered on top of the position list — a failure
      // here shouldn't surface an error banner over an otherwise-fine table.
      .catch(() => {})
      .finally(() => setFuturesQuotesLoading(false))
  }, [futuresData])

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

  // A grouped ratio-spread row's own strike_price ("$7,695/$7,640") and
  // quantity ("1:2") are display-only composites — toNumber() on either
  // silently produces NaN, which is what broke "Analyze Selected" for these
  // rows after grouping was added. Real per-leg strike/quantity/price live on
  // long_leg/short_leg instead, so such a row expands to two selection
  // entries (one per real leg) rather than one row => one entry.
  function groupLegKeys(row) {
    return [`${row.symbol}::long`, `${row.symbol}::short`]
  }

  function toggleSelected(row, optionType, isFutures) {
    // Futures roots come back stripped of their leading "/" (e.g. "ES", not
    // "/ES") — StrikeLab's chain lookup uses that prefix to route to a
    // futures-option chain instead of an equity one, so it has to be put
    // back here or the graph silently comes back empty.
    const underlyingSymbol = isFutures ? `/${row.ticker}` : row.ticker
    setSelected((prev) => {
      const next = new Map(prev)
      if (row.long_leg && row.short_leg) {
        const [longKey, shortKey] = groupLegKeys(row)
        if (next.has(longKey) || next.has(shortKey)) {
          next.delete(longKey)
          next.delete(shortKey)
        } else {
          next.set(longKey, {
            symbol: underlyingSymbol,
            strike: row.long_leg.strike_price,
            optionType,
            quantity: row.long_leg.amount,
            premium: row.long_leg.trade_price,
            dte: row.days_to_expiry,
          })
          next.set(shortKey, {
            symbol: underlyingSymbol,
            strike: row.short_leg.strike_price,
            optionType,
            quantity: -row.short_leg.amount,
            premium: row.short_leg.trade_price,
            dte: row.days_to_expiry,
          })
        }
        return next
      }
      if (next.has(row.symbol)) {
        next.delete(row.symbol)
      } else {
        next.set(row.symbol, {
          symbol: underlyingSymbol,
          strike: toNumber(row.strike_price),
          optionType,
          quantity: toNumber(row.quantity),
          premium: toNumber(row.trade_price),
          dte: row.days_to_expiry,
        })
      }
      return next
    })
  }

  // Adds a checkbox column bound to `selected`, keyed by the row's symbol
  // (or, for a grouped ratio-spread row, its two synthetic per-leg keys).
  function withSelectCheckbox(columns, optionType, isFutures = false) {
    return [
      {
        key: 'select',
        label: '',
        render: (row) => (
          <input
            type="checkbox"
            checked={
              row.long_leg && row.short_leg
                ? groupLegKeys(row).some((k) => selected.has(k))
                : selected.has(row.symbol)
            }
            onChange={() => toggleSelected(row, optionType, isFutures)}
          />
        ),
      },
      ...columns,
    ]
  }

  // current_price arrives separately (see futuresQuotes above) — this column
  // looks it up by symbol at render time instead of reading it off the row.
  // For a grouped ratio-spread row (long_leg/short_leg present), row.symbol is
  // the synthetic label and never matches a quote key — instead look up each
  // real leg's own symbol and combine them the same way the backend computes
  // net_trade_price: (short_qty * short_price) - (long_qty * long_price).
  function futuresCurrentPriceColumn() {
    return {
      key: 'current_price',
      label: 'Current Price',
      align: 'right',
      render: (row) => {
        if (row.long_leg && row.short_leg) {
          const longPrice = futuresQuotes[row.long_leg.symbol]
          const shortPrice = futuresQuotes[row.short_leg.symbol]
          if (longPrice != null && shortPrice != null) {
            const net = (row.short_leg.amount * shortPrice) - (row.long_leg.amount * longPrice)
            return net >= 0 ? `$${net.toFixed(2)}` : `-$${Math.abs(net).toFixed(2)}`
          }
          return futuresQuotesLoading ? 'Loading...' : '—'
        }
        const price = futuresQuotes[row.symbol]
        if (price != null) return `$${price.toFixed(2)}`
        return futuresQuotesLoading ? 'Loading...' : '—'
      },
    }
  }

  // Unrealized P&L: total_value (trade_price-based cost basis, computed on
  // the backend) minus the same position re-priced at the live quote — so it
  // needs futuresQuotes the same way Current Price does, and can't be a plain
  // data key. cell-positive/cell-negative applied manually since DataTable
  // only auto-colors non-render columns.
  function futuresPnLColumn() {
    return {
      key: 'pl',
      label: 'P&L',
      align: 'right',
      render: (row) => {
        const multiplier = row.multiplier ?? 100
        let currentValue = null
        if (row.long_leg && row.short_leg) {
          const longPrice = futuresQuotes[row.long_leg.symbol]
          const shortPrice = futuresQuotes[row.short_leg.symbol]
          if (longPrice != null && shortPrice != null) {
            currentValue = ((row.short_leg.amount * shortPrice) - (row.long_leg.amount * longPrice)) * multiplier
          }
        } else {
          const price = futuresQuotes[row.symbol]
          if (price != null) currentValue = price * -toNumber(row.quantity) * multiplier
        }
        if (currentValue == null) return futuresQuotesLoading ? 'Loading...' : '—'
        const pl = (row.total_value ?? 0) - currentValue
        const text = pl >= 0 ? `$${pl.toFixed(2)}` : `-$${Math.abs(pl).toFixed(2)}`
        return <span className={pl > 0 ? 'cell-positive' : pl < 0 ? 'cell-negative' : ''}>{text}</span>
      },
    }
  }

  function handleAnalyzeSelected() {
    navigate('/analyze', {
      state: {
        analyzePositions: Array.from(selected.values()),
        view: 'graph',
      },
    })
  }

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">Positions</h2>
      </div>

      <div className="tab-bar">
        <div className="tab-row">
          <button
            type="button"
            className={`tab-item ${tab === 'equity' ? 'active' : ''}`}
            onClick={() => setTab('equity')}
          >
            Equity
          </button>
          <button
            type="button"
            className={`tab-item ${tab === 'futures' ? 'active' : ''}`}
            onClick={() => setTab('futures')}
          >
            Futures
          </button>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={selected.size === 0}
          onClick={handleAnalyzeSelected}
        >
          Analyze Selected {selected.size > 0 ? `(${selected.size})` : ''}
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
                    P&amp;L: ${totalPutValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </p>
                  <DataTable data={puts} columns={withSelectCheckbox(OPTION_COLUMNS, 'PUT')} defaultSortKey="days_to_expiry" />
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
                    P&amp;L: ${totalCallValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </p>
                  <DataTable data={calls} columns={withSelectCheckbox(OPTION_COLUMNS, 'CALL')} defaultSortKey="days_to_expiry" />
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
                  <DataTable
                    data={futuresPuts}
                    columns={withSelectCheckbox([...FUTURES_OPTION_COLUMNS, futuresCurrentPriceColumn(), futuresPnLColumn()], 'PUT', true)}
                    defaultSortKey="days_to_expiry"
                  />
                </div>
              ) : (
                <div className="alert warning">No open futures PUT positions found.</div>
              )}

              {/* Futures Calls */}
              {futuresCalls.length > 0 ? (
                <div className="card">
                  <h3 className="section-title">Futures Calls</h3>
                  <DataTable
                    data={futuresCalls}
                    columns={withSelectCheckbox([...FUTURES_OPTION_COLUMNS, futuresCurrentPriceColumn(), futuresPnLColumn()], 'CALL', true)}
                    defaultSortKey="days_to_expiry"
                  />
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
