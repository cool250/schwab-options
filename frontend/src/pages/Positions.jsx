import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getPositions, getFuturesPosition, getFuturesOptionPosition, getMarketQuotes, getOptionQuotes, friendlyErrorMessage } from '../api/client'
import { futuresOptionContracts, futuresOptionRowPl } from '../utils/positionPl'
import { formatOptionSymbol } from '../utils/optionSymbol'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'
import { money, count } from '../utils/numberFormat'

// Survives unmounting/remounting this page (e.g. navigating to Analyze and
// back) within the same browser session — only a full page reload clears it.
// Positions don't change fast enough to justify refetching (and, for futures
// options, re-paying the several-seconds DXLink quote lookup) on every visit.


// broker_cost_basis (Schwab's own tax-lot-aware cost basis — see
// PositionService.get_stock_position) matches trade_price in the common
// case, so showing it as its own column was pure duplication. It only ever
// carries new information when it *diverges* from trade_price (a wash-sale
// adjustment or non-FIFO cost-basis method this app's own reconstruction has
// no way to see) — so it's folded into the Trade Price cell and only
// rendered at all when there's an actual difference to flag.
function stockTradePriceColumn() {
  return {
    key: 'trade_price',
    label: 'Trade Price',
    align: 'right',
    render: (row) => (
      row.broker_cost_basis != null && Math.abs(row.broker_cost_basis - (row.trade_price ?? 0)) >= 0.005
        ? `${money(row.trade_price)} (broker: ${money(row.broker_cost_basis)})`
        : money(row.trade_price)
    ),
  }
}

// Positions arrive as plain numbers; prices/strikes/quantities are formatted
// here (P&L and exposure keep DataTable's own number formatting + coloring).
const quantityColumn = { key: 'quantity', label: 'Quantity', align: 'right', render: (row) => count(row.quantity) }
const tradePriceColumn = { key: 'trade_price', label: 'Trade Price', align: 'right', render: (row) => money(row.trade_price) }
const currentPriceColumn = { key: 'current_price', label: 'Current Price', align: 'right', render: (row) => money(row.current_price, 3) }

const STOCK_COLUMNS = [
  { key: 'symbol',              label: 'Symbol' },
  quantityColumn,
  stockTradePriceColumn(),
  currentPriceColumn,
  { key: 'broker_pl',           label: 'P&L',                align: 'right' },
]

// PUT/CALL has to come from the caller (which table this column set is
// being built for) on both equity and futures option rows here — unlike
// Transactions' rows, a position row has no option_type field of its own,
// since it's only known from which of the two tables (Puts vs Calls) it's
// rendered in. A grouped ratio-spread row (long_leg/short_leg present, see
// toggleSelected et al.) has no single strike, so it falls back to the
// row's own synthetic symbol.
function positionOptionSymbol(row, optionType) {
  if (row.long_leg && row.short_leg) return row.symbol
  return formatOptionSymbol(row.ticker, row.expiration_date, row.strike_price, optionType) ?? row.symbol
}

// A ratio spread shows both strikes ("$7,695/$7,640") and its ratio ("1:2")
// where a single contract shows its strike and quantity.
const strikeColumn = {
  key: 'strike_price',
  label: 'Strike',
  // Explicit: a ratio row's strike_price is null, which DataTable would
  // otherwise left-align while the numeric single-contract rows go right.
  align: 'right',
  render: (row) => (row.long_leg && row.short_leg
    ? `${money(row.long_leg.strike_price, 0)}/${money(row.short_leg.strike_price, 0)}`
    : money(row.strike_price, 0)),
}

// Equity multiplier: one stock option covers 100 shares.
const EQUITY_OPTION_MULTIPLIER = 100

// Position theta in dollars per day: per-share theta x signed contracts x
// multiplier, so a short option's time decay shows as a positive figure. A
// grouped ratio-spread row sums its two real legs (long_leg/short_leg amounts
// are unsigned). null when any leg's theta isn't known.
function positionTheta(row, thetas, multiplier) {
  if (row.long_leg && row.short_leg) {
    const longTheta = thetas[row.long_leg.symbol]
    const shortTheta = thetas[row.short_leg.symbol]
    if (longTheta == null || shortTheta == null) return null
    return (row.long_leg.amount * longTheta - row.short_leg.amount * shortTheta) * multiplier
  }
  const theta = thetas[row.symbol]
  return theta == null || row.quantity == null ? null : theta * row.quantity * multiplier
}

// Theta isn't a row field — it comes from Market's live greeks (POST
// /api/market/quotes), fetched after the table renders, like the futures
// tables' prices. cell-positive/negative applied by hand, as DataTable only
// auto-colors plain key columns.
function thetaColumn(thetas, loading, multiplierOf) {
  return {
    key: 'theta',
    label: 'Theta ($/day)',
    align: 'right',
    render: (row) => {
      const value = positionTheta(row, thetas, multiplierOf(row))
      if (value == null) return loading ? 'Loading...' : '—'
      return <span className={value > 0 ? 'cell-positive' : value < 0 ? 'cell-negative' : ''}>{money(value)}</span>
    },
  }
}

// Summary-line total of positionTheta over `rows`, e.g. "$12.34". Like the
// futures P&L total: if some rows have no theta it sums the rest and says
// how many are missing, rather than passing a partial total off as complete.
function thetaTotalText(rows, thetas, loading, multiplierOf) {
  const values = rows.map((row) => positionTheta(row, thetas, multiplierOf(row)))
  const known = values.filter((v) => v != null)
  if (known.length === 0) return loading ? 'Loading...' : '—'
  const total = known.reduce((sum, v) => sum + v, 0)
  let text = `${money(total)}/day`
  if (known.length < rows.length) text += loading ? ' (loading…)' : ` (${rows.length - known.length} unknown)`
  return text
}

function optionColumns(optionType, theta) {
  return [
    { key: 'ticker',          label: 'Ticker' },
    strikeColumn,
    { key: 'days_to_expiry',  label: 'DTE',         align: 'right' },
    quantityColumn,
    tradePriceColumn,
    currentPriceColumn,
    { key: 'total_value',     label: 'P&L',          align: 'right' },
    theta,
    { key: 'exposure',        label: 'Exposure',     align: 'right' },
    { key: 'symbol',          label: 'Symbol', render: (row) => positionOptionSymbol(row, optionType) },
  ]
}

// current_price isn't part of this — get_futures_position() doesn't return
// it (see the futuresContractQuotes lazy-load below), so it's added as its
// own render-based column (futuresContractCurrentPriceColumn) instead of a
// plain key, same pattern as the futures-option tables' Current Price.
const FUTURES_COLUMNS = [
  { key: 'symbol',      label: 'Symbol' },
  quantityColumn,
  tradePriceColumn,
]

// Same column set, order, and labels as optionColumns() above minus
// Exposure (Ticker, Strike, DTE, Quantity, Trade Price, [Current Price],
// [P&L], [Theta], Symbol) — Current Price, P&L and Theta aren't included here since they
// depend on futuresQuotes (component state) and have to be composed in at
// the call site, same as futuresCurrentPriceColumn/futuresPnLColumn already
// were; Symbol is split out the same way, via futuresSymbolColumn below, so
// it can be spliced in last to match the equity table's order instead of
// sitting second like a plain key column naturally would.
function futuresOptionColumns() {
  return [
    { key: 'ticker',          label: 'Ticker' },
    strikeColumn,
    { key: 'days_to_expiry',  label: 'DTE',         align: 'right' },
    { ...quantityColumn, render: (row) => row.ratio ?? count(row.quantity) },
    tradePriceColumn,
  ]
}

function futuresSymbolColumn(optionType) {
  return { key: 'symbol', label: 'Symbol', render: (row) => positionOptionSymbol(row, optionType) }
}


export default function Positions() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('futures') // 'futures' | 'equity'
  // Account data is loaded fresh on every visit — never cached in memory,
  // so it can't carry over to another user signing in on the same tab.
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

  // current_price for futures options is fetched separately, after the
  // position list itself, so the table renders with everything except price
  // right away instead of blocking on the slow DXLink lookup. Keyed by symbol.
  const [futuresQuotes, setFuturesQuotes] = useState({})
  const [futuresQuotesLoading, setFuturesQuotesLoading] = useState(false)
  // Per-share theta from the same quote request, keyed the same way.
  const [futuresThetas, setFuturesThetas] = useState({})

  // Theta for the equity Puts/Calls tables — Schwab prices them, but its
  // quotes carry no greeks, so theta comes from Market. Keyed by row symbol.
  const [equityThetas, setEquityThetas] = useState({})
  const [equityThetasLoading, setEquityThetasLoading] = useState(false)

  // Same idea, for the outright Futures table — keyed by root symbol (e.g.
  // "ES"), not a contract symbol, so it's a separate state/cache from
  // futuresQuotes above rather than sharing one dict.
  const [futuresContractQuotes, setFuturesContractQuotes] = useState({})
  const [futuresContractQuotesLoading, setFuturesContractQuotesLoading] = useState(false)

  // Options picked (across either tab) to send to StrikeLab — keyed by the
  // row's own symbol, since that's unique per contract.
  const [selected, setSelected] = useState(new Map())
  const [analyzeError, setAnalyzeError] = useState(null)

  useEffect(() => {
    let cancelled = false // nothing lands after unmount (an account switch remounts the page)
    getPositions()
      .then((d) => !cancelled && setData(d))
      .catch((err) => {
        if (!cancelled) setError(friendlyErrorMessage(err, 'Failed to load positions. Make sure the API server is running.'))
      })
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    // Deliberately excludes futuresLoading from the guard/deps: including it
    // turned every failure into an infinite retry loop (loading -> false ->
    // effect re-fires because futuresData is still null -> clears the error
    // -> fails again), so the error banner never stayed on screen long enough
    // to read. Re-fetching now only happens on an actual tab switch.
    if (tab !== 'futures' || futuresData) return
    let cancelled = false
    setFuturesLoading(true)
    setFuturesError(null)
    Promise.all([getFuturesPosition(), getFuturesOptionPosition()])
      .then(([futures, futuresOptions]) => {
        if (!cancelled) setFuturesData({ futures, ...futuresOptions })
      })
      .catch((err) => {
        if (!cancelled) setFuturesError(friendlyErrorMessage(err, 'Failed to load futures positions. Make sure the API server is running.'))
      })
      .finally(() => !cancelled && setFuturesLoading(false))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, futuresData])

  // Live prices come from Market (Schwab can't quote futures or futures
  // options): every real contract on the page — both legs of a grouped
  // ratio-spread row — keyed by its symbol. Two requests, so each table
  // fills in as soon as its own prices land.
  useEffect(() => {
    if (!futuresData) return
    const contracts = futuresOptionContracts(futuresData.puts, futuresData.calls)
    setFuturesQuotesLoading(true)
    getOptionQuotes(contracts)
      .then((quotes) => {
        const bids = {}
        const thetas = {}
        for (const [key, q] of Object.entries(quotes)) {
          if (q.bid != null) bids[key] = q.bid
          if (q.theta != null) thetas[key] = q.theta
        }
        setFuturesQuotes(bids)
        setFuturesThetas(thetas)
      })
      // Prices are a nicety layered on top of the position list — a failure
      // here shouldn't surface an error banner over an otherwise-fine table.
      .catch(() => {})
      .finally(() => setFuturesQuotesLoading(false))
  }, [futuresData])

  useEffect(() => {
    if (!data) return
    const contracts = []
    for (const [rows, type] of [[data.puts ?? [], 'PUT'], [data.calls ?? [], 'CALL']]) {
      for (const row of rows) {
        if (!row.expiration_date) continue
        contracts.push({ key: row.symbol, underlying: row.ticker, expiration: row.expiration_date, strike: row.strike_price, type })
      }
    }
    if (!contracts.length) return
    let cancelled = false
    setEquityThetasLoading(true)
    getOptionQuotes(contracts)
      .then((quotes) => {
        if (cancelled) return
        const thetas = {}
        for (const [key, q] of Object.entries(quotes)) if (q.theta != null) thetas[key] = q.theta
        setEquityThetas(thetas)
      })
      .catch(() => {}) // a nicety on top of the table, like the futures prices
      .finally(() => !cancelled && setEquityThetasLoading(false))
    return () => { cancelled = true }
  }, [data])

  useEffect(() => {
    if (!futuresData) return
    const roots = (futuresData.futures ?? []).map((f) => f.symbol).filter(Boolean)
    if (!roots.length) return
    setFuturesContractQuotesLoading(true)
    getMarketQuotes({ futures: roots })
      .then((quotes) => setFuturesContractQuotes(quotes.futures))
      .catch(() => {})
      .finally(() => setFuturesContractQuotesLoading(false))
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
  // Rows with no live quote have no P&L (null) — say so beside the total
  // rather than letting it silently cover fewer positions.
  const unpricedNote = (rows) => {
    const n = rows.filter((r) => r.total_value == null).length
    return n ? ` (${n} unpriced)` : ''
  }
  const totalStockPL = stocks.reduce((sum, s) => sum + (s.broker_pl ?? 0), 0)

  // A grouped ratio-spread row has no single strike or quantity — its real
  // per-leg strike/quantity/price live on long_leg/short_leg, so such a row
  // expands to two selection entries (one per real leg).
  function groupLegKeys(row) {
    return [`${row.symbol}::long`, `${row.symbol}::short`]
  }

  function toggleSelected(row, optionType, isFutures) {
    // Futures roots come back stripped of their leading "/" (e.g. "ES", not
    // "/ES") — StrikeLab's chain lookup uses that prefix to route to a
    // futures-option chain instead of an equity one, so it has to be put
    // back here or the graph silently comes back empty.
    const underlyingSymbol = isFutures ? `/${row.ticker}` : row.ticker
    setAnalyzeError(null)
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
            ticker: row.ticker,
            expirationDate: row.expiration_date,
          })
          next.set(shortKey, {
            symbol: underlyingSymbol,
            strike: row.short_leg.strike_price,
            optionType,
            quantity: -row.short_leg.amount,
            premium: row.short_leg.trade_price,
            dte: row.days_to_expiry,
            ticker: row.ticker,
            expirationDate: row.expiration_date,
          })
        }
        return next
      }
      if (next.has(row.symbol)) {
        next.delete(row.symbol)
      } else {
        next.set(row.symbol, {
          symbol: underlyingSymbol,
          strike: row.strike_price,
          optionType,
          quantity: row.quantity,
          premium: row.trade_price,
          dte: row.days_to_expiry,
          ticker: row.ticker,
          expirationDate: row.expiration_date,
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

  // Outright futures contracts (not options) — current_price arrives
  // separately (see futuresContractQuotes above), keyed by root symbol
  // directly since there's no grouping concept here like the option tables.
  function futuresContractCurrentPriceColumn() {
    return {
      key: 'current_price',
      label: 'Current Price',
      align: 'right',
      render: (row) => {
        const price = futuresContractQuotes[row.symbol]
        if (price != null) return money(price)
        return futuresContractQuotesLoading ? 'Loading...' : '—'
      },
    }
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
            return money(net)
          }
          return futuresQuotesLoading ? 'Loading...' : '—'
        }
        const price = futuresQuotes[row.symbol]
        if (price != null) return money(price)
        return futuresQuotesLoading ? 'Loading...' : '—'
      },
    }
  }

  // Unrealized P&L: total_value (trade_price-based cost basis, computed on
  // the backend) minus the same position re-priced at the live quote — so it
  // needs futuresQuotes the same way Current Price does, and can't be a plain
  // data key. Null until that row's quote(s) are in. Shared with Reports'
  // unrealized total (utils/openPositions.js).
  function futuresRowPL(row) {
    return futuresOptionRowPl(row, futuresQuotes)
  }

  // cell-positive/cell-negative applied manually since DataTable only
  // auto-colors non-render columns.
  function futuresPnLColumn() {
    return {
      key: 'pl',
      label: 'P&L',
      align: 'right',
      render: (row) => {
        const pl = futuresRowPL(row)
        if (pl == null) return futuresQuotesLoading ? 'Loading...' : '—'
        const text = money(pl)
        return <span className={pl > 0 ? 'cell-positive' : pl < 0 ? 'cell-negative' : ''}>{text}</span>
      },
    }
  }

  // Summary line over a futures-option table, matching the equity tables'
  // "Total: N | P&L: $X". The P&L total waits for the live quotes; if some
  // rows never got one, it sums the rest and says how many are missing
  // rather than presenting a partial total as complete.
  function futuresSummary(rows) {
    const pls = rows.map(futuresRowPL)
    const priced = pls.filter((pl) => pl != null)
    let plText
    if (priced.length === 0) {
      plText = futuresQuotesLoading ? 'Loading...' : '—'
    } else {
      const total = priced.reduce((sum, pl) => sum + pl, 0)
      plText = `${total < 0 ? '-' : ''}$${Math.abs(total).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      if (priced.length < rows.length) {
        plText += futuresQuotesLoading ? ' (loading…)' : ` (${rows.length - priced.length} unpriced)`
      }
    }
    return (
      <p className="summary-line">
        Total: {rows.length}&nbsp;&nbsp;|&nbsp;&nbsp;P&amp;L: {plText}&nbsp;&nbsp;|&nbsp;&nbsp;
        Theta: {thetaTotalText(rows, futuresThetas, futuresQuotesLoading, futuresMultiplier)}
      </p>
    )
  }

  const equityMultiplier = () => EQUITY_OPTION_MULTIPLIER
  const futuresMultiplier = (row) => row.multiplier ?? 100
  const equityThetaColumn = thetaColumn(equityThetas, equityThetasLoading, equityMultiplier)
  const futuresThetaColumn = thetaColumn(futuresThetas, futuresQuotesLoading, futuresMultiplier)
  const equityThetaTotal = (rows) => thetaTotalText(rows, equityThetas, equityThetasLoading, equityMultiplier)

  // StrikeLab's payoff graph prices one spot for one underlying at one point
  // in time — legs from different tickers or different expirations can't be
  // combined into a single meaningful graph, so this is checked up front
  // rather than letting Analyze silently plot a nonsensical mix.
  function handleAnalyzeSelected() {
    const positions = Array.from(selected.values())
    const tickers = new Set(positions.map((p) => p.ticker))
    const expirations = new Set(positions.map((p) => p.expirationDate))
    if (tickers.size > 1 || expirations.size > 1) {
      setAnalyzeError(
        'Select options for a single ticker and expiration date to analyze together.'
      )
      return
    }
    setAnalyzeError(null)
    navigate('/analyze', {
      state: {
        analyzePositions: positions,
        view: 'graph',
      },
    })
  }

  return (
    <div className="page">
      <div className="tab-bar">
        <div className="tab-row">
          <button
            type="button"
            className={`tab-item ${tab === 'futures' ? 'active' : ''}`}
            onClick={() => setTab('futures')}
          >
            Futures
          </button>
          <button
            type="button"
            className={`tab-item ${tab === 'equity' ? 'active' : ''}`}
            onClick={() => setTab('equity')}
          >
            Equity
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

      {analyzeError && <div className="alert error">{analyzeError}</div>}

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
                  {balances.mutual_fund_value != null && (
                    <div className="metric">
                      <span className="metric-label">Mutual Fund</span>
                      <span className="metric-value">
                        ${balances.mutual_fund_value.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                      </span>
                    </div>
                  )}
                  {balances.account_value != null && (
                    <div className="metric">
                      <span className="metric-label">Account Value</span>
                      <span className="metric-value highlight">
                        ${balances.account_value.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Stocks */}
              {stocks.length > 0 ? (
                <div className="card">
                  <h3 className="section-title">Stocks</h3>
                  <p className="summary-line">
                    Total: {stocks.length}&nbsp;&nbsp;|&nbsp;&nbsp;
                    P&amp;L: ${totalStockPL.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </p>
                  <DataTable data={stocks} columns={STOCK_COLUMNS} defaultSortKey="symbol" />
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
                    P&amp;L: ${totalPutValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}{unpricedNote(puts)}&nbsp;&nbsp;|&nbsp;&nbsp;
                    Theta: {equityThetaTotal(puts)}
                  </p>
                  <DataTable data={puts} columns={withSelectCheckbox(optionColumns('PUT', equityThetaColumn), 'PUT')} defaultSortKey="days_to_expiry" />
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
                    P&amp;L: ${totalCallValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}{unpricedNote(calls)}&nbsp;&nbsp;|&nbsp;&nbsp;
                    Theta: {equityThetaTotal(calls)}
                  </p>
                  <DataTable data={calls} columns={withSelectCheckbox(optionColumns('CALL', equityThetaColumn), 'CALL')} defaultSortKey="days_to_expiry" />
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
                  <DataTable data={futures} columns={[...FUTURES_COLUMNS, futuresContractCurrentPriceColumn()]} defaultSortKey="symbol" />
                </div>
              ) : (
                <div className="alert warning">No open futures positions found.</div>
              )}

              {/* Futures Puts */}
              {futuresPuts.length > 0 ? (
                <div className="card">
                  <h3 className="section-title">Puts</h3>
                  {futuresSummary(futuresPuts)}
                  <DataTable
                    data={futuresPuts}
                    columns={withSelectCheckbox([...futuresOptionColumns(), futuresCurrentPriceColumn(), futuresPnLColumn(), futuresThetaColumn, futuresSymbolColumn('PUT')], 'PUT', true)}
                    defaultSortKey="days_to_expiry"
                  />
                </div>
              ) : (
                <div className="alert warning">No open futures PUT positions found.</div>
              )}

              {/* Futures Calls */}
              {futuresCalls.length > 0 ? (
                <div className="card">
                  <h3 className="section-title">Calls</h3>
                  {futuresSummary(futuresCalls)}
                  <DataTable
                    data={futuresCalls}
                    columns={withSelectCheckbox([...futuresOptionColumns(), futuresCurrentPriceColumn(), futuresPnLColumn(), futuresThetaColumn, futuresSymbolColumn('CALL')], 'CALL', true)}
                    defaultSortKey="days_to_expiry"
                  />
                </div>
              ) : (
                <div className="alert warning">No open futures CALL positions found.</div>
              )}

            </>
          )}
        </>
      )}
    </div>
  )
}
