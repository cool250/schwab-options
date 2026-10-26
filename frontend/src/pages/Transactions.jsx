import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getAppConfig, getOptionTransactions, getOptionBids, getEquityTransactions, getIncomeAndFees, friendlyErrorMessage } from '../api/client'
import { getMultiplier, isFuturesRoot } from '../utils/contractMultiplier'
import { formatDate } from '../utils/dateFormat'
import { formatOptionSymbol } from '../utils/optionSymbol'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

// A `render` column formats the display only — DataTable still sorts by the
// raw row[key] (ISO "YYYY-MM-DD", which sorts chronologically), so this
// can't just be a plain-key column reformatted in place. Falls back to '—'
// for a null date (e.g. close_date on a still-open row), matching what
// DataTable's own default cell formatting would otherwise show.
function dateColumn(key, label, align) {
  return { key, label, align, render: (row) => (row[key] ? formatDate(row[key]) : '—') }
}

// A grouped ratio-spread row has no single strike (see long_leg/short_leg)
// — formatOptionSymbol returns null for that, so this keeps the row's
// existing synthetic "N:M Ratio" label instead, which doesn't fit the
// one-strike template.
function optionSymbolCell(row) {
  return formatOptionSymbol(row.underlying_symbol, row.expirationDate, row.strike_price, row.option_type) ?? row.symbol
}

const OPTION_COLUMNS = [
  { key: 'symbol', label: 'Symbol', render: optionSymbolCell },
  { key: 'strike_price', label: 'Strike', align: 'right' },
  dateColumn('date', 'Opened Date'),
  dateColumn('close_date', 'Closed Date'),
  { key: 'open_type',     label: 'Opened As' },
  { key: 'qty',           label: 'Quantity',     align: 'right' },
  { key: 'open_price',     label: 'Cost basis',  align: 'right' },
  { key: 'close_price',   label: 'Closing Price',  align: 'right' },
  { key: 'total_amount',     label: 'Total Gain/Loss ($)',  align: 'right' },
  { key: 'type',     label: 'Status' },
]

const EQUITY_COLUMNS = [
  { key: 'symbol',       label: 'Symbol' },
  dateColumn('date', 'Opened'),
  dateColumn('close_date', 'Closed'),
  { key: 'asset_type',   label: 'Asset Type' },
  { key: 'quantity',     label: 'Quantity',    align: 'right' },
  { key: 'open_price',   label: 'Open Price',  align: 'right' },
  { key: 'close_price',  label: 'Close Price', align: 'right' },
  { key: 'total_amount', label: 'Total',       align: 'right' },
  { key: 'status',       label: 'Status' },
]

// The All tab: options, equity & futures, and (optionally) income and fees
// in one table, on the columns they share. A contract's strike and
// expiration sit in its name; the other tabs keep their own columns.
const ALL_COLUMNS = [
  dateColumn('date', 'Opened'),
  dateColumn('close_date', 'Closed'),
  { key: 'kind',         label: 'Type' },
  { key: 'label',        label: 'Contract / Symbol' },
  { key: 'qty',          label: 'Quantity',    align: 'right' },
  { key: 'open_price',   label: 'Open Price',  align: 'right' },
  { key: 'close_price',  label: 'Close Price', align: 'right' },
  { key: 'total_amount', label: 'Total Gain/Loss ($)', align: 'right' },
  { key: 'status',       label: 'Status' },
]
const ASSET_KIND = { EQUITY: 'Stock', FUTURE: 'Future' }
const INCOME_LABEL = {
  INTEREST: 'Interest', MARGIN_INTEREST: 'Margin interest', DIVIDEND: 'Dividend',
  SHORT_DIVIDEND: 'Dividend on a short', MONEY_FUND_DIVIDEND: 'Money fund dividend',
}

// An equity/futures row as the Equity & futures tab shows it. A still-open
// lot (long, or short: negative quantity) has no gain/loss yet, so its
// total shows 0. A close whose opening fill is outside the lookback comes
// with open_unknown, no open date or price, and a total of 0.
function normalizeEquityRow(t) {
  return t.close_price == null ? { ...t, total_amount: 0 } : t
}

function firstOfMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

function todayStr() {
  return new Date().toISOString().split('T')[0]
}

// Exports exactly what's on screen — same columns (in the same order,
// including a render column like Current Price, which returns a plain
// string here) and the same row data DataTable is currently showing.
function downloadCsv(filename, columns, rows) {
  const escape = (val) => {
    const s = val == null ? '' : String(val)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const header = columns.map((c) => escape(c.label)).join(',')
  const lines = rows.map((row) => columns.map((c) => escape(c.render ? c.render(row) : row[c.key])).join(','))
  const blob = new Blob([[header, ...lines].join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// A crisp inline SVG instead of an emoji glyph — renders identically across
// OS/browsers (unlike ⬇️, which varies a lot) and inherits the button's own
// color via currentColor, so it already matches dark mode with no extra work.
function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v11" />
      <path d="M7.5 10.5 12 15l4.5-4.5" />
      <path d="M4 19h16" />
    </svg>
  )
}

function DownloadCsvButton({ onClick }) {
  return (
    <button type="button" className="btn btn-secondary icon-btn" title="Download as CSV" onClick={onClick}>
      <DownloadIcon />
      <span>CSV</span>
    </button>
  )
}

// Survives unmounting/remounting this page (e.g. navigating to Reports and
// back) within the same browser session — only a full page reload or an
// explicit new search clears it. Without this, switching tabs away and back
// silently re-ran the last search and threw away whatever the user was
// looking at.


export default function Transactions() {
  const [searchParams] = useSearchParams()
  // A chart-click link (e.g. from Reports) always carries its own ticker/dates
  // and should run a fresh search rather than restoring whatever was cached.
  const fromLink = Boolean(searchParams.get('ticker') || searchParams.get('start'))
  const urlTab = ['equity', 'options', 'all'].includes(searchParams.get('tab')) ? searchParams.get('tab') : null
  // An incoming link with no explicit ?tab= (the options-chart click-through)
  // means "options" specifically, not whatever tab happened to be cached —
  // only a plain revisit (no link params at all) should restore the cache.
  const initialTab = urlTab ?? 'options'
  const [tab, setTab] = useState(initialTab) // 'options' | 'equity' | 'all'

  // Searches and results are not cached between visits: account data is
  // always loaded fresh for whoever is signed in.
  const cachedOptions = null
  const cachedEquity = null

  // One ticker for both tabs: typed on either, it's there on the other
  // (both searches accept a stock ticker or a futures root, with or without "/").
  const [ticker, setTicker] = useState(searchParams.get('ticker')?.toUpperCase() ?? '')

  // ---- Option transactions ----
  const [contractType, setContractType] = useState(cachedOptions?.contractType ?? 'ALL')
  const [ignoreFutures, setIgnoreFutures] = useState(cachedOptions?.ignoreFutures ?? false)
  const [ignoreGrouping, setIgnoreGrouping] = useState(cachedOptions?.ignoreGrouping ?? false)
  // Which rows to show: closed (realized) legs, still-open (unrealized)
  // legs, or both. At least one stays checked. A link's ?realized=false with
  // no ?unrealized (the old "show everything") opens with both checked.
  const [[showRealized, showUnrealized], setShown] = useState(() => {
    const realizedParam = initialTab === 'options' ? searchParams.get('realized') : null
    const unrealizedParam = initialTab === 'options' ? searchParams.get('unrealized') : null
    const realized = realizedParam ? realizedParam !== 'false' : cachedOptions?.showRealized ?? true
    const unrealized = unrealizedParam ? unrealizedParam === 'true' : cachedOptions?.showUnrealized ?? false
    return realized || unrealized ? [realized, unrealized] : [true, true]
  })
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

  async function runSearch(tickerVal, startVal, endVal, contractTypeVal, ignoreFuturesVal, ignoreGroupingVal, realizedVal, unrealizedVal) {
    setLoading(true)
    setError(null)
    setTransactions(null)
    setOptionQuotes({})
    try {
      const tickerUpper = tickerVal.trim().toUpperCase()
      // Both checked = no filter: the API's two flags each narrow to one side.
      const data = await getOptionTransactions(
        tickerUpper, startVal, endVal, contractTypeVal,
        realizedVal && !unrealizedVal, unrealizedVal && !realizedVal, !ignoreGroupingVal,
      )
      // Ignore Futures is a separate asset-class filter, not a PUT/CALL/ALL
      // value the backend's contract_type understands — applied client-side
      // instead, on top of whichever contract_type was requested.
      const filtered = ignoreFuturesVal
        ? data.filter((t) => !isFuturesRoot(t.underlying_symbol))
        : data
      setTransactions(filtered)

      // Current price for still-open (TRADE) rows comes from Market
      // (Tastytrade; Schwab can't quote futures options) — fetched
      // separately so the table itself renders immediately instead of
      // blocking on it. Keyed by each contract's own symbol.
      const open = filtered.filter((t) => t.type === 'TRADE' && t.strike_price != null)
      if (open.length > 0) {
        setOptionQuotesLoading(true)
        getOptionBids(open.map((t) => ({
          key: t.symbol, underlying: t.underlying_symbol, expiration: t.expirationDate,
          strike: t.strike_price, type: t.option_type,
        })))
          .then(setOptionQuotes)
          .catch(() => {})
          .finally(() => setOptionQuotesLoading(false))
      }
    } catch (err) {
      setError(friendlyErrorMessage(err, 'Failed to fetch transactions. Make sure the API server is running.'))
    } finally {
      setLoading(false)
    }
  }

  function handleSearch(e) {
    e.preventDefault()
    runSearch(ticker, startDate, endDate, contractType, ignoreFutures, ignoreGrouping, showRealized, showUnrealized)
  }

  // Defaults for Ignore Grouping and the realized/unrealized boxes come from
  // config/app.properties (trades.group_ratio_spreads,
  // transactions.default_view) via GET /api/config — on both tabs; on
  // Equity & futures, "realized" ticks Realized Gains Only and "both" or
  // "unrealized" leaves it unticked (that tab has no unrealized-only view).
  // A box the user already changed, or one a link set through the URL, is
  // left alone.
  const linkSetView = Boolean(searchParams.get('realized') || searchParams.get('unrealized'))
  const touched = useRef({
    grouping: false,
    view: initialTab === 'options' && linkSetView,
    equityView: initialTab === 'equity' && linkSetView,
    allView: initialTab === 'all' && linkSetView,
  })

  // Arriving from a chart click (e.g. Reports) pre-fills the filters via the
  // URL — run the search immediately instead of waiting for another click,
  // once the settings above have loaded (or failed to).
  useEffect(() => {
    let cancelled = false
    getAppConfig()
      .catch(() => null) // keep the built-in defaults
      .then((config) => {
        if (cancelled) return
        let grouping = ignoreGrouping
        let [realized, unrealized] = [showRealized, showUnrealized]
        if (config && !touched.current.grouping) {
          grouping = !config['trades.group_ratio_spreads']
          setIgnoreGrouping(grouping)
        }
        const view = config?.['transactions.default_view']
        if (view && !touched.current.view) {
          ;[realized, unrealized] = [view !== 'unrealized', view !== 'realized']
          setShown([realized, unrealized])
        }
        let equityRealized = equityRealizedOnly
        if (view && !touched.current.equityView) {
          equityRealized = view === 'realized'
          setEquityRealizedOnly(equityRealized)
        }
        let [allRealized, allUnrealized] = [allShowRealized, allShowUnrealized]
        if (view && !touched.current.allView) {
          ;[allRealized, allUnrealized] = [view !== 'unrealized', view !== 'realized']
          setAllShown([allRealized, allUnrealized])
        }
        if (initialTab === 'options' && fromLink) {
          runSearch(ticker, startDate, endDate, contractType, ignoreFutures, grouping, realized, unrealized)
        }
        if (initialTab === 'equity' && fromLink) {
          runEquitySearch(ticker, equityStartDate, equityEndDate, assetType, equityRealized)
        }
        if (initialTab === 'all' && fromLink) {
          runAllSearch(ticker, allStartDate, allEndDate, allRealized, allUnrealized, includeIncome, grouping)
        }
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The Total column doubles as both figures rather than needing a separate
  // Unrealized Gain column: a still-open leg's total_amount as returned by
  // the API is just its entry credit/debit (not a completed gain), so swap
  // it here for the live-priced unrealized gain instead — a row is either
  // realized (closed, shows its real total_amount) or unrealized (open,
  // shows its unrealized gain), never both, so one column covers it.
  // null while the live quote hasn't loaded yet, rendered as "—" by DataTable.
  //
  // Also exposes the API's `amount` (contract count — or a "N:M" label on a
  // grouped ratio-spread row) as `qty` for the Quantity column: DataTable
  // auto-colors any field whose name contains "amount" as a gain/loss, and
  // a quantity isn't one.
  const optionRows = (transactions ?? []).map((raw) => {
    const t = { ...raw, qty: raw.amount }
    if (t.type !== 'TRADE') return t
    const price = optionQuotes[t.symbol]
    if (price == null) return { ...t, total_amount: null }
    return { ...t, total_amount: t.amount * getMultiplier(t.underlying_symbol) * (price - t.open_price) }
  })

  // The summary line's realized "Total" stays realized-only — computed from
  // the raw transactions (not optionRows, whose total_amount now mixes in
  // unrealized figures for open rows) so it isn't diluted by unrealized P&L.
  const totalAmount = (transactions ?? []).reduce((s, t) => s + (t.type === 'TRADE' ? 0 : (t.total_amount ?? 0)), 0)

  // Still-open rows' total_amount is null until optionQuotes loads (see
  // optionRows above) — a render column so it can show "Loading..." instead
  // of DataTable's default "—" for null, matching the Positions page pattern
  // (futuresPnLColumn). getCellClass's automatic coloring is skipped for
  // render columns, so it's reapplied manually here.
  function totalAmountColumn() {
    return {
      key: 'total_amount',
      label: 'Total Gain/Loss ($)',
      align: 'right',
      render: (row) => {
        const val = row.total_amount
        if (val == null) return row.type === 'TRADE' && optionQuotesLoading ? 'Loading...' : '—'
        const text = val.toLocaleString('en-US', { maximumFractionDigits: 2 })
        return <span className={val > 0 ? 'cell-positive' : val < 0 ? 'cell-negative' : ''}>{text}</span>
      },
    }
  }

  // A still-open row has no close_price yet — reuses the same Closing Price
  // column to show its live current price instead of a separate column, the
  // same one-column-covers-both approach as totalAmountColumn above. Live
  // current price isn't a field on the row itself; it depends on the quote
  // fetched separately (see optionQuotes above).
  function closePriceColumn() {
    return {
      key: 'close_price',
      label: 'Closing Price',
      align: 'right',
      render: (row) => {
        if (row.type !== 'TRADE') {
          return row.close_price != null ? row.close_price.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—'
        }
        const price = optionQuotes[row.symbol]
        if (price != null) return `$${price.toFixed(2)}`
        return optionQuotesLoading ? 'Loading...' : '—'
      },
    }
  }

  // Live pricing is relevant whenever open rows can appear, i.e. whenever
  // Unrealized is checked (alone, or with Realized for open and closed rows
  // mixed). Realized alone never has open rows, so its plain
  // close_price/total_amount columns are left as-is.
  const showLivePricing = showUnrealized
  const optionColumns = showLivePricing
    ? OPTION_COLUMNS.map((c) => {
        if (c.key === 'close_price') return closePriceColumn()
        if (c.key === 'total_amount') return totalAmountColumn()
        return c
      })
    : OPTION_COLUMNS

  const totalUnrealizedGain = showLivePricing
    ? (transactions ?? []).reduce((s, t) => {
        const price = optionQuotes[t.symbol]
        return price == null ? s : s + t.amount * getMultiplier(t.underlying_symbol) * (price - t.open_price)
      }, 0)
    : null

  // ---- Equity / futures transactions ----
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

  async function runEquitySearch(tickerVal, startVal, endVal, assetTypeVal, realizedVal) {
    setEquityLoading(true)
    setEquityError(null)
    setEquityTransactions(null)
    try {
      const data = await getEquityTransactions(tickerVal.trim().toUpperCase(), startVal, endVal, assetTypeVal, realizedVal)
      setEquityTransactions(data)
    } catch (err) {
      setEquityError(friendlyErrorMessage(err, 'Failed to fetch transactions. Make sure the API server is running.'))
    } finally {
      setEquityLoading(false)
    }
  }

  function handleEquitySearch(e) {
    e.preventDefault()
    runEquitySearch(ticker, equityStartDate, equityEndDate, assetType, equityRealizedOnly)
  }

  // Either way — an open lot (no close yet) or a close with no open on
  // record — there's no way to compute a real gain/loss without both legs,
  // so Total shows 0 until a full round-trip is on record.
  const equityRows = (equityTransactions ?? []).map(normalizeEquityRow)
  const equityTotalAmount = equityRows.reduce((s, t) => s + (t.total_amount ?? 0), 0)

  // ---- All: options + equity & futures (+ income and fees) ----
  // Its own dates and realized/unrealized boxes, like the other tabs; the
  // ticker is shared. A link from Reports sets them (?tab=all, and
  // ?income=true when it came from the running total, which counts
  // dividends, interest and fees).
  const [[allShowRealized, allShowUnrealized], setAllShown] = useState(() => {
    const realizedParam = initialTab === 'all' ? searchParams.get('realized') : null
    const unrealizedParam = initialTab === 'all' ? searchParams.get('unrealized') : null
    const realized = realizedParam ? realizedParam !== 'false' : true
    const unrealized = unrealizedParam ? unrealizedParam === 'true' : false
    return realized || unrealized ? [realized, unrealized] : [true, true]
  })
  const [includeIncome, setIncludeIncome] = useState(initialTab === 'all' ? searchParams.get('income') === 'true' : false)
  const [allStartDate, setAllStartDate] = useState(() => (initialTab === 'all' ? searchParams.get('start') ?? firstOfMonth() : firstOfMonth()))
  const [allEndDate, setAllEndDate] = useState(() => (initialTab === 'all' ? searchParams.get('end') ?? todayStr() : todayStr()))
  const [allLoading, setAllLoading] = useState(false)
  const [allError, setAllError] = useState(null)
  const [allData, setAllData] = useState(null) // { options, equity, income }
  const [allQuotes, setAllQuotes] = useState({})
  const [allQuotesLoading, setAllQuotesLoading] = useState(false)

  async function runAllSearch(tickerVal, startVal, endVal, realizedVal, unrealizedVal, incomeVal, ignoreGroupingVal) {
    setAllLoading(true)
    setAllError(null)
    setAllData(null)
    setAllQuotes({})
    try {
      const tickerUpper = tickerVal.trim().toUpperCase()
      const realizedOnly = realizedVal && !unrealizedVal
      const unrealizedOnly = unrealizedVal && !realizedVal
      const [options, equity, income] = await Promise.all([
        getOptionTransactions(tickerUpper, startVal, endVal, 'ALL', realizedOnly, unrealizedOnly, !ignoreGroupingVal),
        // The equity API has no unrealized-only view: ask for everything and
        // keep the open rows.
        getEquityTransactions(tickerUpper, startVal, endVal, 'ALL', realizedOnly)
          .then((rows) => (unrealizedOnly ? rows.filter((t) => t.close_price == null && !(t.quantity < 0)) : rows)),
        // Income and fees belong to the account, not a ticker.
        incomeVal && !tickerUpper && realizedVal ? getIncomeAndFees(startVal, endVal) : Promise.resolve([]),
      ])
      setAllData({ options, equity, income })
      const open = options.filter((t) => t.type === 'TRADE' && t.strike_price != null)
      if (open.length > 0) {
        setAllQuotesLoading(true)
        getOptionBids(open.map((t) => ({
          key: t.symbol, underlying: t.underlying_symbol, expiration: t.expirationDate,
          strike: t.strike_price, type: t.option_type,
        })))
          .then(setAllQuotes)
          .catch(() => {})
          .finally(() => setAllQuotesLoading(false))
      }
    } catch (err) {
      setAllError(friendlyErrorMessage(err, 'Failed to fetch transactions. Make sure the API server is running.'))
    } finally {
      setAllLoading(false)
    }
  }

  function handleAllSearch(e) {
    e.preventDefault()
    runAllSearch(ticker, allStartDate, allEndDate, allShowRealized, allShowUnrealized, includeIncome, ignoreGrouping)
  }

  // One row shape for all three. An open option leg is priced at its live
  // bid (its unrealized gain), as on the Options tab.
  const allOptionRows = (allData?.options ?? []).map((t) => {
    const base = {
      ...t, kind: 'Option', label: optionSymbolCell(t), qty: t.amount,
      status: t.type === 'TRADE' ? 'OPEN' : t.type,
    }
    if (t.type !== 'TRADE') return base
    const price = allQuotes[t.symbol]
    return {
      ...base,
      close_price: price ?? null,
      total_amount: price == null ? null : t.amount * getMultiplier(t.underlying_symbol) * (price - t.open_price),
    }
  })
  const allEquityRows = (allData?.equity ?? []).map(normalizeEquityRow).map((t) => ({
    ...t, kind: ASSET_KIND[t.asset_type] ?? t.asset_type, label: t.symbol, qty: t.quantity,
  }))
  const allIncomeRows = (allData?.income ?? []).map((r) => ({
    close_date: r.date, date: null, kind: r.kind === 'FEE' ? 'Fee' : 'Income',
    label: r.kind === 'FEE' ? r.description || r.category : INCOME_LABEL[r.category] ?? r.category,
    total_amount: r.amount, status: r.category,
  }))
  const allRows = [...allOptionRows, ...allEquityRows, ...allIncomeRows]
  const sumRealized = (rows) => rows.reduce((s, t) => s + (t.status === 'OPEN' ? 0 : (t.total_amount ?? 0)), 0)
  const allTotals = {
    options: sumRealized(allOptionRows),
    equity: sumRealized(allEquityRows),
    income: sumRealized(allIncomeRows),
  }
  const allUnrealized = allOptionRows.reduce((s, t) => s + (t.status === 'OPEN' ? (t.total_amount ?? 0) : 0), 0)
  const allColumns = ALL_COLUMNS.map((c) => (c.key !== 'total_amount' ? c : {
    ...c,
    render: (row) => {
      const val = row.total_amount
      if (val == null) return row.status === 'OPEN' && allQuotesLoading ? 'Loading...' : '—'
      const text = val.toLocaleString('en-US', { maximumFractionDigits: 2 })
      return <span className={val > 0 ? 'cell-positive' : val < 0 ? 'cell-negative' : ''}>{text}</span>
    },
  }))
  const usd = (v) => `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

  return (
    <div className="page">
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
        <button
          type="button"
          className={`tab-item ${tab === 'all' ? 'active' : ''}`}
          onClick={() => setTab('all')}
        >
          All
        </button>
      </div>

      {tab === 'all' ? (
        <>
          <div className="card">
            <form onSubmit={handleAllSearch}>
              <div className="form-row">
                <div className="form-group">
                  <label>Ticker / Futures Root</label>
                  <input
                    type="text"
                    value={ticker}
                    onChange={(e) => setTicker(e.target.value.toUpperCase())}
                    placeholder="e.g. AAPL, ES (blank = all)"
                    className="input"
                  />
                </div>
                <div className="form-group">
                  <label>From Date</label>
                  <input type="date" value={allStartDate} onChange={(e) => setAllStartDate(e.target.value)} className="input" />
                </div>
                <div className="form-group">
                  <label>To Date</label>
                  <input type="date" value={allEndDate} onChange={(e) => setAllEndDate(e.target.value)} className="input" />
                </div>
              </div>

              <div className="form-actions">
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={allShowRealized}
                    disabled={allShowRealized && !allShowUnrealized}
                    onChange={(e) => { touched.current.allView = true; setAllShown([e.target.checked, allShowUnrealized]) }}
                    className="toggle-checkbox"
                  />
                  <span>Realized Gains</span>
                </label>
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={allShowUnrealized}
                    disabled={allShowUnrealized && !allShowRealized}
                    onChange={(e) => { touched.current.allView = true; setAllShown([allShowRealized, e.target.checked]) }}
                    className="toggle-checkbox"
                  />
                  <span>Unrealized Gains</span>
                </label>
                <label className="toggle-label" title="Dividends, interest and fees — for the whole account, so not with a ticker">
                  <input
                    type="checkbox"
                    checked={includeIncome}
                    onChange={(e) => setIncludeIncome(e.target.checked)}
                    className="toggle-checkbox"
                  />
                  <span>Income &amp; Fees</span>
                </label>
                <button type="submit" className="btn btn-primary" disabled={allLoading}>
                  Search Transactions
                </button>
              </div>
            </form>
          </div>

          {allError && <div className="alert error">{allError}</div>}
          {allLoading && <Spinner />}

          {allData && !allLoading && (
            allRows.length === 0 ? (
              <div className="alert warning">No transactions found for the given criteria.</div>
            ) : (
              <div className="card">
                <div className="section-header">
                  <h3 className="section-title">Transactions</h3>
                  <span className="summary-line">
                    {allRows.length} records &nbsp;|&nbsp; Total: {usd(allTotals.options + allTotals.equity + allTotals.income)}
                    {' '}(Options {usd(allTotals.options)} · Equity &amp; futures {usd(allTotals.equity)}
                    {allIncomeRows.length > 0 && <> · Income &amp; fees {usd(allTotals.income)}</>})
                    {allShowUnrealized && <>&nbsp;|&nbsp; Unrealized Gain: {usd(allUnrealized)}</>}
                  </span>
                  <DownloadCsvButton
                    onClick={() => downloadCsv(`all-transactions_${allStartDate}_to_${allEndDate}.csv`, ALL_COLUMNS, allRows)}
                  />
                </div>
                <DataTable data={allRows} columns={allColumns} defaultSortKey="close_date" defaultSortDir="desc" defaultPageSize={10} />
              </div>
            )
          )}
        </>
      ) : tab === 'options' ? (
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
                    checked={showRealized}
                    disabled={showRealized && !showUnrealized}
                    onChange={(e) => { touched.current.view = true; setShown([e.target.checked, showUnrealized]) }}
                    className="toggle-checkbox"
                  />
                  <span>Realized Gains</span>
                </label>
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={showUnrealized}
                    disabled={showUnrealized && !showRealized}
                    onChange={(e) => { touched.current.view = true; setShown([showRealized, e.target.checked]) }}
                    className="toggle-checkbox"
                  />
                  <span>Unrealized Gains</span>
                </label>
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={ignoreFutures}
                    onChange={(e) => setIgnoreFutures(e.target.checked)}
                    className="toggle-checkbox"
                  />
                  <span>Ignore Futures</span>
                </label>
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={ignoreGrouping}
                    onChange={(e) => { touched.current.grouping = true; setIgnoreGrouping(e.target.checked) }}
                    className="toggle-checkbox"
                  />
                  <span>Ignore Grouping</span>
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
                    <DownloadCsvButton
                      onClick={() => downloadCsv(`option-transactions_${startDate}_to_${endDate}.csv`, optionColumns, optionRows)}
                    />
                  </div>
                  <DataTable data={optionRows} columns={optionColumns} defaultSortKey="close_date" defaultSortDir="desc" defaultPageSize={10} />
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
                    value={ticker}
                    onChange={(e) => setTicker(e.target.value.toUpperCase())}
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
                    onChange={(e) => { touched.current.equityView = true; setEquityRealizedOnly(e.target.checked) }}
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
                    <DownloadCsvButton
                      onClick={() => downloadCsv(`equity-transactions_${equityStartDate}_to_${equityEndDate}.csv`, EQUITY_COLUMNS, equityRows)}
                    />
                  </div>
                  <DataTable data={equityRows} columns={EQUITY_COLUMNS} defaultSortKey="close_date" defaultSortDir="desc" defaultPageSize={10} />
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
