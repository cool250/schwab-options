import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAllocations, getEquityTransactions, getOptionTransactions, getOptionBids, friendlyErrorMessage } from '../api/client'
import { getMultiplier } from '../utils/contractMultiplier'
import Spinner from '../components/Spinner'
import {
  KpiStrip, MonthCalendar, DailyRunChart, SymbolTable,
  MonthlyBarsChart, CumulativeChart, SymbolMonthHeat, YearCalendar, SourceTabs,
} from '../components/ReportViews'
import { closedTrades, tradeStats, openTradeStats, symbolBreakdown, symbolOf, todayIso, utcDate, addDays, MONTH_NAMES } from '../utils/reportStats'

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

export default function Reports() {
  const [defaults] = useState(reportDefaults)
  const navigate = useNavigate()
  const [period, setPeriod] = useState(defaults.period) // 'month' | 'ytd'
  const [year, setYear] = useState(defaults.year)
  const [month, setMonth] = useState(defaults.month)
  // Per tab: what was last loaded for it — the period plus the raw rows
  // (options, equity/futures, and, for Month, last month's options) —
  // whether it's loading, and its error. Each tab keeps its own, so
  // switching between Month and YTD doesn't refetch.
  const [reports, setReports] = useState({ month: null, ytd: null })
  const [loadingFor, setLoadingFor] = useState({ month: false, ytd: false })
  const [errors, setErrors] = useState({ month: null, ytd: null })
  // Latest request per tab, so a slow earlier response can't overwrite a
  // newer one (e.g. Submit pressed twice).
  const requestIds = useRef({ month: 0, ytd: 0 })
  const report = reports[period]
  const loading = loadingFor[period]
  const error = errors[period]
  // Which trades the by-symbol tables show — options, equity & futures, or
  // both. One setting for both tables and both tabs.
  const [source, setSource] = useState('options') // 'options' | 'equity' | 'all'

  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear() - i)

  // Month view: still-open option trades expiring in the shown month (today
  // or later), each priced at its live bid like Transactions' unrealized
  // view — { year, month, legs: [{ expiration, unrealized }], loading }.
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

  async function load(period, year, month) {
    if (period === 'month') loadOpen(year, month)
    const id = ++requestIds.current[period]
    const current = () => requestIds.current[period] === id
    setLoadingFor((s) => ({ ...s, [period]: true }))
    setErrors((s) => ({ ...s, [period]: null }))
    setReports((s) => ({ ...s, [period]: null }))
    try {
      const { start, end } = period === 'ytd' ? ytdRange(year) : monthRange(year, month)
      // Month compares against last month; YTD has no comparison.
      const prevMonth = period === 'month' ? previousMonth(year, month) : null
      const prevRange = prevMonth && monthRange(prevMonth.year, prevMonth.month)
      const prevName = prevMonth ? MONTH_NAMES[prevMonth.month - 1] : null
      const [data, equityData, prevData] = await Promise.all([
        getAllocations(start, end, REALIZED_ONLY),
        getEquityTransactions('', start, end, 'ALL', REALIZED_ONLY),
        // Only for the "vs last month" comparison — the report still loads
        // without it.
        prevRange ? getAllocations(prevRange.start, prevRange.end, REALIZED_ONLY).catch(() => null) : Promise.resolve(null),
      ])
      if (!current()) return
      setReports((s) => ({ ...s, [period]: {
        period, year, month, start, end,
        label: period === 'ytd' ? `${year} year to date` : `${monthName(month)} ${year}`,
        optionRows: withDay(normalizeOptionRows(data ?? [])),
        equityRows: withDay(normalizeEquityRows(equityData ?? [])),
        prevOptionRows: prevData ? withDay(normalizeOptionRows(prevData)) : null,
        prevName,
      } }))
    } catch (err) {
      if (current()) setErrors((s) => ({ ...s, [period]: friendlyErrorMessage(err, 'Failed to fetch report data. Make sure the API server is running.') }))
    } finally {
      if (current()) setLoadingFor((s) => ({ ...s, [period]: false }))
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    load(period, year, month)
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

  function selectPeriod(p) {
    setPeriod(p)
    if (!reports[p] && !loadingFor[p]) load(p, year, month)
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
    const traded = Array.from({ length: lastMonth + 1 }, (_, m) =>
      tradeStats(optionTrades.filter((t) => utcDate(t.close_date).getUTCMonth() === m))).filter((st) => st.n > 0)
    return {
      optionTrades,
      equityTrades,
      stats: tradeStats(optionTrades),
      prevStats: report.prevOptionRows ? tradeStats(closedTrades(report.prevOptionRows)) : null,
      equityNet: tradeStats(equityTrades).net,
      today,
      lastMonth,
      positiveMonths: `${traded.filter((st) => st.net > 0).length} of ${traded.length} months positive`,
      yearEnd: isCurrentYear ? today : `${report.year}-12-31`,
    }
  }, [report])

  // By-symbol tables follow the source switch.
  const sourceTrades = !derived ? [] :
    source === 'options' ? derived.optionTrades :
    source === 'equity' ? derived.equityTrades :
    [...derived.optionTrades, ...derived.equityTrades]
  const sourceSymbols = useMemo(() => symbolBreakdown(sourceTrades), [sourceTrades])
  const sourceEmpty = `No ${{ options: 'option ', equity: 'equity or futures ', all: '' }[source]}trades closed in ${report?.label ?? ''}.`

  // ---- Click-through to the matching transactions ----
  function openTransactions({ ticker, start, end, tab }) {
    const params = new URLSearchParams({ start, end, realized: String(REALIZED_ONLY) })
    if (ticker) params.set('ticker', ticker)
    if (tab) params.set('tab', tab)
    navigate(`/transactions?${params}`)
  }
  const monthBounds = (m) => monthRange(report.year, m + 1)
  const openDay = (date) => openTransactions({ start: date, end: date })
  const openWeek = (start, end) => openTransactions({ start, end })
  const openMonth = (m) => openTransactions(monthBounds(m))

  // Transactions shows one tab at a time, so a by-symbol click opens the tab
  // holding those trades — for "All", options when the symbol had any in the
  // range, else equity & futures.
  const monthOfTrade = (t) => utcDate(t.close_date).getUTCMonth()
  const tabFor = (ticker, inRange) => {
    if (source !== 'all') return source === 'equity' ? 'equity' : undefined
    const hasOptions = derived.optionTrades.some((t) => inRange(t) && (ticker == null || symbolOf(t) === ticker))
    return hasOptions ? undefined : 'equity'
  }
  const openSymbol = (ticker) => openTransactions({ ticker, start: report.start, end: report.end, tab: tabFor(ticker, () => true) })
  const openSymbolMonth = (ticker, m) => openTransactions({ ticker, ...monthBounds(m), tab: tabFor(ticker, (t) => monthOfTrade(t) === m) })
  const openSourceMonth = (m) => openTransactions({ ...monthBounds(m), tab: tabFor(null, (t) => monthOfTrade(t) === m) })

  const isMonth = report?.period === 'month'
  // Open trades for the month on screen (not a different one still loading).
  const openNow = isMonth && open && open.year === report.year && open.month === report.month ? open : null
  const openLegs = openNow?.legs ?? []
  const noData = derived && derived.optionTrades.length === 0 && derived.equityTrades.length === 0 && openLegs.length === 0
  const show = derived && !noData && !loading

  return (
    <div className="page">
      <div className="tab-row">
        <button
          type="button"
          className={`tab-item ${period === 'month' ? 'active' : ''}`}
          onClick={() => selectPeriod('month')}
        >
          Month
        </button>
        <button
          type="button"
          className={`tab-item ${period === 'ytd' ? 'active' : ''}`}
          onClick={() => selectPeriod('ytd')}
        >
          YTD
        </button>
      </div>

      <div className="card">
        <form onSubmit={handleSubmit} className="report-filters">
          <div className="form-group">
            <label htmlFor="report-year">Year</label>
            <select id="report-year" value={year} onChange={(e) => setYear(Number(e.target.value))} className="input">
              {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          {period === 'month' && (
            <div className="form-group">
              <label htmlFor="report-month">Month</label>
              <select id="report-month" value={month} onChange={(e) => setMonth(Number(e.target.value))} className="input">
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                  <option key={m} value={m}>{monthName(m)}</option>
                ))}
              </select>
            </div>
          )}
          <button type="submit" className="btn btn-primary" disabled={loading}>
            Submit
          </button>
        </form>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <Spinner />}

      {noData && !loading && (
        <div className="alert warning">No closed trades in {report.label}.</div>
      )}

      {show && (
        <>
          {/* 1. Key numbers — compared with last month in the Month view */}
          <KpiStrip
            stats={derived.stats}
            prev={derived.prevStats}
            prevName={report.prevName}
            netNote={isMonth ? null : derived.positiveMonths}
            extraNet={derived.equityNet}
            open={openNow && (openLegs.length > 0 || openNow.loading)
              ? { stats: openTradeStats(openLegs), loading: openNow.loading, monthName: monthName(report.month) }
              : null}
          />

          {/* 2. P&L by period (left) and the running total (right) — same slots in both views */}
          {(derived.optionTrades.length > 0 || (isMonth && openLegs.length > 0)) && (
            <div className="report-row">
              <div className="card">
                <div className="report-card-head">
                  <h3 className="section-title">{isMonth ? `${monthName(report.month)} calendar` : 'Monthly P&L'}</h3>
                  <span className="report-card-note">
                    {isMonth ? 'Options · click a day or week · dashed days: open trades expiring' : `Options · ${derived.positiveMonths} · click a month`}
                  </span>
                </div>
                {isMonth ? (
                  <MonthCalendar
                    year={report.year}
                    month={report.month}
                    trades={derived.optionTrades}
                    today={derived.today}
                    onDay={openDay}
                    onWeek={openWeek}
                    openLegs={openLegs}
                    openLoading={openNow?.loading ?? false}
                  />
                ) : (
                  <div className="report-chart-fill">
                    <MonthlyBarsChart
                      trades={derived.optionTrades}
                      lastMonth={derived.lastMonth}
                      partialNote={report.year === currentYear() ? 'to date' : null}
                      onMonth={openMonth}
                    />
                  </div>
                )}
              </div>

              <div className="card">
                <div className="report-card-head">
                  <h3 className="section-title">Running total</h3>
                  <span className="report-card-note">Options · click a day to open it</span>
                </div>
                {isMonth && (
                  <div className="report-legend">
                    <span><i className="report-key-bar" style={{ background: 'var(--success)' }} /><i className="report-key-bar" style={{ background: 'var(--error)' }} />Daily P&amp;L</span>
                    <span><i className="report-key-line" />Running total</span>
                  </div>
                )}
                <div className="report-chart-fill">
                  {isMonth
                    ? <DailyRunChart trades={derived.optionTrades} onDay={openDay} />
                    : <CumulativeChart trades={derived.optionTrades} onDay={openDay} />}
                </div>
              </div>
            </div>
          )}

          {/* 3. By symbol — options, equity & futures, or both */}
          <div className="card">
            <div className="report-card-head">
              <h3 className="section-title">By symbol</h3>
              <span className="report-card-note">Click a row to open its transactions</span>
            </div>
            <SourceTabs value={source} onChange={setSource} />
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
                  <span className="report-card-note">Click a cell for that symbol&apos;s trades that month</span>
                </div>
                <SourceTabs value={source} onChange={setSource} />
                {sourceTrades.length > 0 ? (
                  <SymbolMonthHeat
                    trades={sourceTrades}
                    lastMonth={derived.lastMonth}
                    onCell={openSymbolMonth}
                    onMonth={openSourceMonth}
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

              {derived.optionTrades.length > 0 && (
                <div className="card">
                  <div className="report-card-head">
                    <h3 className="section-title">{report.year} calendar</h3>
                    <span className="report-card-note">Options · click a day to open it</span>
                  </div>
                  <YearCalendar year={report.year} trades={derived.optionTrades} endIso={derived.yearEnd} onDay={openDay} />
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
