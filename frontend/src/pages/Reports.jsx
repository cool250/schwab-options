import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAllocations, getEquityTransactions, getIncomeAndFees, getPlacedTrades, getOptionTransactions, getOptionBids, friendlyErrorMessage } from '../api/client'
import { loadOpenPositionsPl } from '../utils/openPositions'
import { getMultiplier, isFuturesRoot } from '../utils/contractMultiplier'
import Spinner from '../components/Spinner'
import TradeDetails from '../components/TradeDetails'
import TaxSummary from '../components/TaxSummary'
import { useMatchMedia } from '../components/DataTable'
import {
  KpiStrip, MonthCalendar, DailyRunChart, SymbolTable,
  MonthGrid, MonthlyRunChart, SymbolMonthHeat, YearCalendar, SourceTabs,
} from '../components/ReportViews'
import { closedTrades, tradeStats, openTradeStats, symbolBreakdown, todayIso, utcDate, addDays, MONTH_NAMES } from '../utils/reportStats'

function monthName(m) {
  return new Date(2000, m - 1, 1).toLocaleString('en-US', { month: 'long' })
}

function currentYear() { return new Date().getFullYear() }
function currentMonth() { return new Date().getMonth() + 1 }

function monthRange(year, month) {
  const start = `${year}-${String(month).padStart(2, '0')}-01`
  const lastDay = new Date(year, month, 0).getDate()
  const end = `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
  return { start, end }
}

// Jan 1 through today (or Dec 31 for a past year). Today is the local
// calendar date, not toISOString()'s UTC one, which runs a day ahead in a
// US evening.
function ytdRange(year) {
  const start = `${year}-01-01`
  const end = year === currentYear() ? todayIso() : `${year}-12-31`
  return { start, end }
}

function previousMonth(year, month) {
  return month === 1 ? { year: year - 1, month: 12 } : { year, month: month - 1 }
}

// Same normalization Transactions.jsx applies to equity/future rows before
// display: an unmatched leg — either a still-open position, or a closing
// sale whose original open fell outside the backend's lookback window — has
// no real gain/loss it can compute, so its total_amount (left as the raw
// cash flow, e.g. a closing sale's full proceeds) must be zeroed rather than
// summed as if it were realized P&L. Without this, a stale close like a
// 200-share CRM sale shows its entire $40,000 in proceeds as "profit".
function normalizeEquityRows(rows) {
  return rows.map((t) => {
    if (t.quantity < 0) {
      return { ...t, close_date: t.date, close_price: t.open_price, date: null, open_price: null, status: 'CLOSED', total_amount: 0 }
    }
    return t.close_price == null ? { ...t, total_amount: 0 } : t
  })
}

// Option-side counterpart to normalizeEquityRows: a still-open leg (Schwab's
// own raw "TRADE" type, not yet promoted to CLOSED/EXPIRED/ASSIGNED by the
// backend's matcher — see get_option_transactions/_match_trades) carries
// total_amount as its raw entry credit/debit, not a realized gain. Without
// this, a currently-open short position's full premium received gets summed
// in as if it were profit — e.g. a $2,800 credit from an open NQ put spread
// showing up as $2,800 "P&L" for a month it was never closed in.
function normalizeOptionRows(rows) {
  return rows.map((t) => (t.type === 'TRADE' ? { ...t, total_amount: 0 } : t))
}

// Realized P&L by kind: shares, equity options, futures, futures options.
function plSplit(optionTrades, equityTrades) {
  const sum = (rows) => rows.reduce((s, t) => s + (t.total_amount ?? 0), 0)
  const futuresOption = (t) => isFuturesRoot(t.underlying_symbol)
  const future = (t) => t.asset_type === 'FUTURE'
  return {
    equity: sum(equityTrades.filter((t) => !future(t))),
    equityOptions: sum(optionTrades.filter((t) => !futuresOption(t))),
    futures: sum(equityTrades.filter(future)),
    futuresOptions: sum(optionTrades.filter(futuresOption)),
  }
}

// { income, fees, incomeBy, feesBy } of getIncomeAndFees rows — totals, and
// { [category]: dollars } for each kind — or null when they didn't load.
function incomeFeeTotals(rows) {
  if (!rows) return null
  const out = { income: 0, fees: 0, incomeBy: {}, feesBy: {} }
  for (const r of rows) {
    const amount = r.amount ?? 0
    const [key, by] = r.kind === 'INCOME' ? ['income', out.incomeBy] : ['fees', out.feesBy]
    out[key] += amount
    by[r.category] = (by[r.category] ?? 0) + amount
  }
  return out
}

// "N of M months positive" over the months (through lastMonth, 0-based)
// that had a closed trade.
function monthsPositive(trades, lastMonth) {
  const net = Array(lastMonth + 1).fill(null)
  for (const t of trades) {
    const m = utcDate(t.close_date).getUTCMonth()
    if (m <= lastMonth) net[m] = (net[m] ?? 0) + (t.total_amount ?? 0)
  }
  const traded = net.filter((v) => v != null)
  return `${traded.filter((v) => v > 0).length} of ${traded.length} months positive`
}

// Calendar date only — the views key everything by "YYYY-MM-DD".
const withDay = (rows) => rows.map((t) => (t.close_date ? { ...t, close_date: String(t.close_date).slice(0, 10) } : t))

// Starting state for each visit — reports are not cached between visits, so
// account data is always loaded fresh for whoever is signed in.
const reportDefaults = () => ({
  period: 'month', year: currentYear(), month: currentMonth(),
})

// The P&L figures cover realized (closed) trades; the Month view adds the
// still-open ones expiring in that month separately (loadOpen below).
const REALIZED_ONLY = true

// How far back to look for still-open option legs — the same reconstruction
// the Transactions page's Unrealized view uses (Schwab caps a request at a
// year), so the two pages agree.
const OPEN_LOOKBACK_DAYS = 360

const TABS = [
  { id: 'month', label: 'Month' },
  { id: 'ytd', label: 'YTD' },
  { id: 'trades', label: 'Trade Details' },
  { id: 'tax', label: 'Tax summary' },
]
// Trade Details and Tax summary cover the same Jan 1 – today range as YTD.
const isYearTab = (p) => p === 'ytd' || p === 'trades' || p === 'tax'
const PRINT_TITLES = { month: 'Monthly report', ytd: 'Year-to-date report', trades: 'Trade Details', tax: 'Tax summary' }

// Wait for layout and paint: the charts resize themselves (ResizeObserver)
// to the print-mode width before the print dialog snapshots the page.
const settle = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 350))))

export default function Reports() {
  const [defaults] = useState(reportDefaults)
  const navigate = useNavigate()
  const [period, setPeriod] = useState(defaults.period) // 'month' | 'ytd' | 'trades'
  const [year, setYear] = useState(defaults.year)
  const [month, setMonth] = useState(defaults.month)
  // Per tab: what was last loaded for it — the period plus the raw rows
  // (options, equity/futures, and, for Month, last month's options) —
  // whether it's loading, and its error. Each tab keeps its own, so
  // switching between tabs doesn't refetch.
  const [reports, setReports] = useState({ month: null, ytd: null, trades: null, tax: null })
  const [loadingFor, setLoadingFor] = useState({ month: false, ytd: false, trades: false, tax: false })
  const [errors, setErrors] = useState({ month: null, ytd: null, trades: null, tax: null })
  // Latest request per tab, so a slow earlier response can't overwrite a
  // newer one (e.g. the year changed twice in quick succession).
  const requestIds = useRef({ month: 0, ytd: 0, trades: 0, tax: 0 })
  // What each tab last asked for (loaded or still loading): { year, month }.
  const requestedFor = useRef({ month: null, ytd: null, trades: null, tax: null })
  // Export PDF: the header printed above the report (title, period, account,
  // date), set just before printing.
  const [printHead, setPrintHead] = useState(null)
  const report = reports[period]
  const loading = loadingFor[period]
  const error = errors[period]
  // Which trades the calendars, running totals and by-symbol tables show —
  // options, equity & futures, or both. One setting for every view and both tabs.
  const [source, setSource] = useState('all') // 'options' | 'equity' | 'all'

  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear() - i)

  // Month view: still-open option trades expiring in the shown month (today
  // or later), each priced at its live bid like Transactions' unrealized
  // view — { year, month, legs: [{ expiration, unrealized, atExpiry }], loading }.
  const [open, setOpen] = useState(null)
  const openRequestId = useRef(0)

  async function loadOpen(year, month) {
    const id = ++openRequestId.current
    const current = () => openRequestId.current === id
    const { start, end } = monthRange(year, month)
    const today = todayIso()
    if (end < today) { // nothing in a past month is still open
      setOpen({ year, month, legs: [], loading: false })
      return
    }
    setOpen({ year, month, legs: [], loading: true })
    try {
      // An open leg's close_date is its expiration, and the backend keeps
      // only rows closing inside the range — so the range has to run to the
      // month's end, not today, or legs expiring after today are dropped.
      // The lookback counts from there too, keeping the span under a year.
      const rows = await getOptionTransactions('', addDays(end, -OPEN_LOOKBACK_DAYS), end, 'ALL', false, true, false)
      if (!current()) return
      const from = start > today ? start : today
      const legs = (rows ?? []).filter((t) => t.type === 'TRADE' && t.expirationDate >= from && t.expirationDate <= end)
      const priced = (bids) => legs.map((t) => ({
        expiration: t.expirationDate,
        unrealized: bids[t.symbol] == null ? null : t.amount * getMultiplier(t.underlying_symbol) * (bids[t.symbol] - t.open_price),
        // If it expires worthless: a short keeps its premium, a long loses its cost.
        atExpiry: -t.amount * getMultiplier(t.underlying_symbol) * t.open_price,
      }))
      setOpen({ year, month, legs: priced({}), loading: legs.length > 0 })
      if (!legs.length) return
      const bids = await getOptionBids(legs.map((t) => ({
        key: t.symbol, underlying: t.underlying_symbol, expiration: t.expirationDate, strike: t.strike_price, type: t.option_type,
      }))).catch(() => ({}))
      if (current()) setOpen({ year, month, legs: priced(bids), loading: false })
    } catch {
      // A nicety on top of the realized report — leave it out rather than fail the page.
      if (current()) setOpen(null)
    }
  }

  // YTD view, current year: unrealized P&L of every position open right
  // now (utils/openPositions.js) — { year, loading, data, failed }.
  const [unrealized, setUnrealized] = useState(null)
  const unrealizedRequestId = useRef(0)

  async function loadUnrealized(year) {
    const id = ++unrealizedRequestId.current
    if (year !== currentYear()) { setUnrealized(null); return } // a past year's open positions aren't "now"
    setUnrealized({ year, loading: true, data: null, failed: false })
    try {
      const data = await loadOpenPositionsPl()
      if (unrealizedRequestId.current === id) setUnrealized({ year, loading: false, data, failed: false })
    } catch {
      // Like the Month view's open trades: a nicety on top of the realized report.
      if (unrealizedRequestId.current === id) setUnrealized({ year, loading: false, data: null, failed: true })
    }
  }

  async function load(period, year, month) {
    if (period === 'month') loadOpen(year, month)
    if (period === 'ytd' || period === 'tax') loadUnrealized(year)
    const id = ++requestIds.current[period]
    requestedFor.current[period] = { year, month }
    const current = () => requestIds.current[period] === id
    setLoadingFor((s) => ({ ...s, [period]: true }))
    setErrors((s) => ({ ...s, [period]: null }))
    setReports((s) => ({ ...s, [period]: null }))
    try {
      const { start, end } = isYearTab(period) ? ytdRange(year) : monthRange(year, month)
      // Month compares against last month; YTD has no comparison.
      const prevMonth = period === 'month' ? previousMonth(year, month) : null
      const prevRange = prevMonth && monthRange(prevMonth.year, prevMonth.month)
      const prevName = prevMonth ? MONTH_NAMES[prevMonth.month - 1] : null
      const [data, equityData, prevData, prevEquityData, incomeFees, prevIncomeFees, placed] = await Promise.all([
        getAllocations(start, end, REALIZED_ONLY),
        getEquityTransactions('', start, end, 'ALL', REALIZED_ONLY),
        // Only for the "vs last month" comparison — the report still loads
        // without them.
        prevRange ? getAllocations(prevRange.start, prevRange.end, REALIZED_ONLY).catch(() => null) : Promise.resolve(null),
        prevRange ? getEquityTransactions('', prevRange.start, prevRange.end, 'ALL', REALIZED_ONLY).catch(() => null) : Promise.resolve(null),
        // Dividends, interest and fees: shown beside the trade P&L — the
        // report still loads without them.
        getIncomeAndFees(start, end).catch(() => null),
        prevRange ? getIncomeAndFees(prevRange.start, prevRange.end).catch(() => null) : Promise.resolve(null),
        // Trade Details: the trades placed (null if they didn't load — the
        // tab says so).
        period === 'trades' ? getPlacedTrades(start, end).catch(() => null) : Promise.resolve(null),
      ])
      if (!current()) return
      setReports((s) => ({ ...s, [period]: {
        period, year, month, start, end,
        label: isYearTab(period) ? `${year} year to date` : `${monthName(month)} ${year}`,
        placed,
        optionRows: withDay(normalizeOptionRows(data ?? [])),
        equityRows: withDay(normalizeEquityRows(equityData ?? [])),
        prevOptionRows: prevData ? withDay(normalizeOptionRows(prevData)) : null,
        prevEquityRows: prevEquityData ? withDay(normalizeEquityRows(prevEquityData)) : null,
        incomeFees,
        prevIncomeFees,
        prevName,
      } }))
    } catch (err) {
      if (current()) setErrors((s) => ({ ...s, [period]: friendlyErrorMessage(err, 'Failed to fetch report data. Make sure the API server is running.') }))
    } finally {
      if (current()) setLoadingFor((s) => ({ ...s, [period]: false }))
    }
  }

  // A dropdown change loads the report for it straight away.
  function changeYear(y) {
    setYear(y)
    load(period, y, month)
  }

  function changeMonth(m) {
    setMonth(m)
    load('month', year, m)
  }

  // A sideways swipe on the daily calendar steps a month back or forward
  // (touch screens), within the years the Year dropdown offers and never
  // past the current month.
  function shiftMonth(delta) {
    const index = year * 12 + (month - 1) + delta
    const y = Math.floor(index / 12), m = (index % 12) + 1
    if (y < yearOptions[yearOptions.length - 1] || y * 12 + m > currentYear() * 12 + currentMonth()) return
    setYear(y)
    setMonth(m)
    load('month', y, m)
  }
  const swipeable = useMatchMedia('(hover: none)')
  const swipeStart = useRef(null)
  const swipe = {
    onTouchStart: (e) => { swipeStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY } },
    onTouchEnd: (e) => {
      const start = swipeStart.current
      swipeStart.current = null
      if (!start) return
      const dx = e.changedTouches[0].clientX - start.x
      const dy = e.changedTouches[0].clientY - start.y
      if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) shiftMonth(dx < 0 ? 1 : -1)
    },
  }

  // The current month loads as soon as the page opens; YTD loads the
  // selected year the first time its tab is opened.
  const loadedOnMount = useRef(false)
  useEffect(() => {
    if (loadedOnMount.current) return // StrictMode runs effects twice in dev
    loadedOnMount.current = true
    load('month', year, month)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Switching tabs reuses that tab's report (loaded or loading) only if it
  // was asked for the current year (and month); a dropdown changed on the
  // other tab means a reload.
  function selectPeriod(p) {
    setPeriod(p)
    const asked = requestedFor.current[p]
    const matches = asked && asked.year === year && (isYearTab(p) || asked.month === month)
    if (!matches || errors[p]) load(p, year, month) // a failed load is retried
  }

  const derived = useMemo(() => {
    if (!report) return null
    const optionTrades = closedTrades(report.optionRows)
    // Equity rows with no matched open are zeroed above — not real trades.
    const equityTrades = closedTrades(report.equityRows, { dropZero: true })
    const today = todayIso()
    const isCurrentYear = report.year === currentYear()
    // YTD: the months shown run through the current one (this year) or
    // December (a past year).
    const lastMonth = isCurrentYear ? new Date().getMonth() : 11
    return {
      optionTrades,
      equityTrades,
      stats: tradeStats(optionTrades),
      prevStats: report.prevOptionRows ? tradeStats(closedTrades(report.prevOptionRows)) : null,
      equityNet: tradeStats(equityTrades).net,
      split: plSplit(optionTrades, equityTrades),
      prevEquityNet: report.prevEquityRows ? tradeStats(closedTrades(report.prevEquityRows, { dropZero: true })).net : null,
      incomeFees: incomeFeeTotals(report.incomeFees),
      prevIncomeFees: incomeFeeTotals(report.prevIncomeFees),
      today,
      lastMonth,
      yearEnd: isCurrentYear ? today : `${report.year}-12-31`,
    }
  }, [report])

  // Every view below the key numbers follows the source switch.
  const sourceTrades = useMemo(() => !derived ? [] :
    source === 'options' ? derived.optionTrades :
    source === 'equity' ? derived.equityTrades :
    [...derived.optionTrades, ...derived.equityTrades], [derived, source])
  // The running total always covers every trade, whatever the switch says.
  const allTrades = useMemo(() => !derived ? [] : [...derived.optionTrades, ...derived.equityTrades], [derived])
  // The running total also adds dividends, interest and fees on the day they
  // were booked (marked `cash`, so they don't count as trades), so it ends at
  // Total P&L's realized figure.
  const runningRows = useMemo(() => [
    ...allTrades,
    ...(report?.incomeFees ?? []).map((r) => ({ close_date: r.date, total_amount: r.amount, cash: true })),
  ], [allTrades, report])
  const sourceSymbols = useMemo(() => symbolBreakdown(sourceTrades), [sourceTrades])
  const sourceLabel = { options: 'Options', equity: 'Equity & futures', all: 'All trades' }[source]
  // "7 of 10 months positive": for the shown source on the month grid, for
  // every trade under Total P&L (which counts them all).
  const positiveMonths = useMemo(() => derived ? monthsPositive(sourceTrades, derived.lastMonth) : '', [derived, sourceTrades])
  const allPositiveMonths = useMemo(() => derived ? monthsPositive(allTrades, derived.lastMonth) : '', [derived, allTrades])
  const sourceEmpty = `No ${{ options: 'option ', equity: 'equity or futures ', all: '' }[source]}trades closed in ${report?.label ?? ''}.`

  // ---- Click-through to the matching transactions ----
  // open: the range has still-open trades (Month calendar) — show those too.
  // Which rows Transactions shows (realized / unrealized) is left to its own
  // default (transactions.default_view) — only a day with open trades asks
  // for the unrealized ones as well.
  // income: the clicked view counts dividends, interest and fees (the
  // running total) — the All tab includes them then.
  function openTransactions({ ticker, start, end, tab, open = false, income = false }) {
    const params = new URLSearchParams({ start, end })
    if (open) params.set('unrealized', 'true')
    if (income) params.set('income', 'true')
    if (ticker) params.set('ticker', ticker)
    if (tab) params.set('tab', tab)
    navigate(`/transactions?${params}`)
  }
  const monthBounds = (m) => monthRange(report.year, m + 1)
  // src: the trades the clicked view shows — the source switch's, or 'all'
  // for the running total (which always covers every trade).
  const openRange = (start, end, open, src = source, income = false) =>
    openTransactions({ start, end, open, income, tab: tabFor(src) })
  const openDay = (date, open) => openRange(date, date, open)
  const openWeek = (start, end, open) => openRange(start, end, open)
  const openMonth = (m) => openRange(monthBounds(m).start, monthBounds(m).end)
  const openAllDay = (date) => openRange(date, date, false, 'all', true)
  const openAllMonth = (m) => openRange(monthBounds(m).start, monthBounds(m).end, false, 'all', true)
  const openQuarter = (q) => openRange(monthBounds(q * 3).start, monthBounds(q * 3 + 2).end)

  // Which Transactions tab a click opens: the source switch's — "All" opens
  // the All tab (options with equity & futures).
  const tabFor = (src = source) => (src === 'all' ? 'all' : src === 'equity' ? 'equity' : undefined)
  const openSymbol = (ticker) => openTransactions({ ticker, start: report.start, end: report.end, tab: tabFor() })
  const openSymbolMonth = (ticker, m) => openTransactions({ ticker, ...monthBounds(m), tab: tabFor() })

  const openTradesMonth = (m) => openRange(monthBounds(m).start, monthBounds(m).end, false, 'all')

  // Trade Details' holding period: every realized trade with a known open
  // — options, and equity/futures round trips ($0 ones included).
  const heldTrades = useMemo(() => (!derived ? [] : [
    ...derived.optionTrades,
    ...closedTrades(report.equityRows).filter((t) => t.date && t.open_price != null),
  ]), [derived, report])

  // ---- Export PDF ----
  // The browser's print dialog, whose "Save as PDF" writes the file. The
  // page is laid out for a landscape sheet first (.print-mode in
  // reports.css) in the light theme, with a header naming the report, its
  // period and the account; everything goes back once the dialog closes.
  async function exportPdf() {
    const html = document.documentElement
    const theme = html.getAttribute('data-theme')
    const title = document.title
    const tab = TABS.find((t) => t.id === period).label
    const account = document.getElementById('account-picker-inline')?.selectedOptions?.[0]?.text ?? null
    setPrintHead({
      title: PRINT_TITLES[period],
      meta: [report.label, account, `Exported ${new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`]
        .filter(Boolean).join(' · '),
    })
    document.title = `${tab} ${report.label}` // the PDF's suggested file name
    html.classList.add('print-mode')
    html.setAttribute('data-theme', 'light')
    const restore = () => {
      html.classList.remove('print-mode')
      if (theme) html.setAttribute('data-theme', theme)
      document.title = title
      setPrintHead(null)
    }
    try {
      await settle()
      window.addEventListener('afterprint', restore, { once: true })
      window.print()
    } catch {
      restore()
    }
  }

  const isMonth = report?.period === 'month'
  // Open trades for the month on screen (not a different one still loading).
  const openNow = isMonth && open && open.year === report.year && open.month === report.month ? open : null
  const openLegs = openNow?.legs ?? []
  // The calendar's dashed days are open option legs — not shown under
  // "Equity & futures". (The key numbers' tile shows them either way.)
  const calendarOpenLegs = source === 'equity' ? [] : openLegs
  const noData = report?.period === 'trades'
    ? report.placed != null && report.placed.trades.length === 0
    : derived && derived.optionTrades.length === 0 && derived.equityTrades.length === 0 && openLegs.length === 0
  const show = derived && !noData && !loading

  return (
    <div className="page">
      <div className="tab-row no-print">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tab-item ${period === t.id ? 'active' : ''}`}
            onClick={() => selectPeriod(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {printHead && (
        <div className="report-print-head">
          <span className="report-print-title">{printHead.title}</span>
          <span className="report-print-meta">{printHead.meta}</span>
        </div>
      )}

      <div className="card no-print">
        <div className="report-filters">
          <div className="form-group">
            <label htmlFor="report-year">Year</label>
            <select id="report-year" value={year} onChange={(e) => changeYear(Number(e.target.value))} className="input">
              {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          {period === 'month' && (
            <div className="form-group">
              <label htmlFor="report-month">Month</label>
              <select id="report-month" value={month} onChange={(e) => changeMonth(Number(e.target.value))} className="input">
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                  <option key={m} value={m}>{monthName(m)}</option>
                ))}
              </select>
            </div>
          )}
          <button type="button" className="btn btn-secondary report-export" onClick={exportPdf} disabled={!show}>
            Export PDF
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <Spinner />}

      {noData && !loading && (
        <div className="alert warning">No {report.period === 'trades' ? 'trades placed' : 'closed trades'} in {report.label}.</div>
      )}

      {show && report.period === 'trades' && (
        <TradeDetails
          placed={report.placed}
          closedTrades={heldTrades}
          start={report.start}
          end={report.end}
          lastMonth={derived.lastMonth}
          label={report.label}
          onMonth={openTradesMonth}
        />
      )}

      {show && report.period === 'tax' && (
        <TaxSummary
          optionTrades={derived.optionTrades}
          equityTrades={derived.equityTrades}
          unrealized={unrealized && unrealized.year === report.year ? unrealized : null}
          incomeFees={derived.incomeFees}
          year={report.year}
          isCurrentYear={report.year === currentYear()}
          lastMonth={derived.lastMonth}
        />
      )}

      {show && report.period !== 'trades' && report.period !== 'tax' && (
        <>
          {/* 1. Key numbers — compared with last month in the Month view */}
          <KpiStrip
            stats={derived.stats}
            prev={derived.prevStats}
            prevName={report.prevName}
            netNote={isMonth ? null : allPositiveMonths}
            extraNet={derived.equityNet}
            split={isMonth ? null : derived.split}
            prevExtraNet={derived.prevEquityNet}
            incomeFees={derived.incomeFees}
            prevIncomeFees={derived.prevIncomeFees}
            unrealized={!isMonth && unrealized && unrealized.year === report.year ? unrealized : null}
            open={openNow && (openLegs.length > 0 || openNow.loading)
              ? { stats: openTradeStats(openLegs), loading: openNow.loading, monthName: monthName(report.month) }
              : null}
          />

          {/* One source switch for every card below it (the running total
              always covers every trade). */}
          <div className="report-source-bar">
            <span className="report-source-label">Show</span>
            <SourceTabs value={source} onChange={setSource} />
          </div>

          {/* 2. P&L by period (left) and the running total (right) — same slots in both views.
              The running total covers every trade, so the row shows whatever the switch says. */}
          <div className="report-row">
            <div className="card">
              <div className="report-card-head">
                <h3 className="section-title">{isMonth ? 'Daily P&L' : 'Monthly P&L'}</h3>
                <span className="report-card-note">
                  {isMonth
                    ? `${sourceLabel} · click a day or week${source === 'equity' ? '' : ' · dashed days: open options expiring'}`
                    + (swipeable ? ' · swipe for another month' : '')
                    : `${sourceLabel} · ${positiveMonths} · click a month or quarter`}
                </span>
              </div>
              {!(sourceTrades.length > 0 || (isMonth && calendarOpenLegs.length > 0)) ? (
                <p className="summary-line">{sourceEmpty}</p>
              ) : isMonth ? (
                <div {...swipe}>
                <MonthCalendar
                  year={report.year}
                  month={report.month}
                  trades={sourceTrades}
                  today={derived.today}
                  onDay={openDay}
                  onWeek={openWeek}
                  openLegs={calendarOpenLegs}
                  openLoading={source !== 'equity' && (openNow?.loading ?? false)}
                />
                </div>
              ) : (
                <MonthGrid
                  trades={sourceTrades}
                  lastMonth={derived.lastMonth}
                  partialNote={report.year === currentYear() ? 'to date' : null}
                  onMonth={openMonth}
                  onQuarter={openQuarter}
                />
              )}
            </div>

            <div className="card">
              <div className="report-card-head">
                <h3 className="section-title">Running total</h3>
                <span className="report-card-note">All trades, income &amp; fees · click a {isMonth ? 'day' : 'month'} to open it</span>
              </div>
              <div className="report-legend">
                <span><i className="report-key-bar" style={{ background: 'var(--success)' }} /><i className="report-key-bar" style={{ background: 'var(--error)' }} />{isMonth ? 'Daily' : 'Monthly'} P&amp;L</span>
                <span><i className="report-key-line" />Running total</span>
              </div>
              <div className="report-chart-fill">
                {isMonth
                  ? <DailyRunChart trades={runningRows} onDay={openAllDay} />
                  : <MonthlyRunChart trades={runningRows} lastMonth={derived.lastMonth} onMonth={openAllMonth} />}
              </div>
            </div>
          </div>

          {/* 3. By symbol — options, equity & futures, or both */}
          <div className="card">
            <div className="report-card-head">
              <h3 className="section-title">By symbol</h3>
              <span className="report-card-note">{sourceLabel} · click a row to open its transactions</span>
            </div>
            {sourceSymbols.length > 0
              ? <SymbolTable rows={sourceSymbols} onSymbol={openSymbol} />
              : <p className="summary-line">{sourceEmpty}</p>}
          </div>

          {/* 4. YTD only: symbol by month, then every trading day */}
          {!isMonth && (
            <>
              <div className="card">
                <div className="report-card-head">
                  <h3 className="section-title">Symbol by month</h3>
                  <span className="report-card-note">{sourceLabel} · click a cell for that symbol&apos;s trades that month</span>
                </div>
                {sourceTrades.length > 0 ? (
                  <SymbolMonthHeat
                    trades={sourceTrades}
                    lastMonth={derived.lastMonth}
                    onCell={openSymbolMonth}
                    onMonth={openMonth}
                  />
                ) : (
                  <p className="summary-line">{sourceEmpty}</p>
                )}
                {source === 'all' && sourceTrades.length > 0 && (
                  <p className="report-footnote">
                    Options and equity &amp; futures combined by symbol, so an exercised futures option&apos;s premium
                    and the delivered future&apos;s result share one row.
                  </p>
                )}
              </div>

              {sourceTrades.length > 0 && (
                <div className="card">
                  <div className="report-card-head">
                    <h3 className="section-title">{report.year} calendar</h3>
                    <span className="report-card-note">{sourceLabel} · click a day to open it</span>
                  </div>
                  <YearCalendar year={report.year} trades={sourceTrades} endIso={derived.yearEnd} onDay={openDay} />
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
