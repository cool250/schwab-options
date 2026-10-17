import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getAllocations, getEquityTransactions, friendlyErrorMessage } from '../api/client'
import Spinner from '../components/Spinner'
import {
  KpiStrip, MonthCalendar, DailyRunChart, SymbolTable,
  MonthlyBarsChart, CumulativeChart, SymbolMonthHeat, YearCalendar,
} from '../components/ReportViews'
import { closedTrades, tradeStats, symbolBreakdown, todayIso, utcDate, MONTH_NAMES } from '../utils/reportStats'

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

// Reports cover realized (closed) P&L only.
const REALIZED_ONLY = true

export default function Reports() {
  const [defaults] = useState(reportDefaults)
  const navigate = useNavigate()
  const [period, setPeriod] = useState(defaults.period) // 'month' | 'ytd'
  const [year, setYear] = useState(defaults.year)
  const [month, setMonth] = useState(defaults.month)
  // Per tab: what was last loaded for it — the period plus the raw rows
  // (options, equity/futures, and the previous month's options for the
  // month view's comparison) — whether it's loading, and its error. Each
  // tab keeps its own, so switching between Month and YTD doesn't refetch.
  const [reports, setReports] = useState({ month: null, ytd: null })
  const [loadingFor, setLoadingFor] = useState({ month: false, ytd: false })
  const [errors, setErrors] = useState({ month: null, ytd: null })
  // Latest request per tab, so a slow earlier response can't overwrite a
  // newer one (e.g. Submit pressed twice).
  const requestIds = useRef({ month: 0, ytd: 0 })
  const report = reports[period]
  const loading = loadingFor[period]
  const error = errors[period]
  // YTD "Symbol by month" source: option trades, equity & futures, or both.
  const [heatSource, setHeatSource] = useState('options') // 'options' | 'equity' | 'all'

  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear() - i)

  async function load(period, year, month) {
    const id = ++requestIds.current[period]
    const current = () => requestIds.current[period] === id
    setLoadingFor((s) => ({ ...s, [period]: true }))
    setErrors((s) => ({ ...s, [period]: null }))
    setReports((s) => ({ ...s, [period]: null }))
    try {
      const { start, end } = period === 'ytd' ? ytdRange(year) : monthRange(year, month)
      const prev = period === 'month' ? previousMonth(year, month) : null
      const prevRange = prev && monthRange(prev.year, prev.month)
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
        prevName: prev ? MONTH_NAMES[prev.month - 1] : null,
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
    return {
      optionTrades,
      equityTrades,
      stats: tradeStats(optionTrades),
      prevStats: report.prevOptionRows ? tradeStats(closedTrades(report.prevOptionRows)) : null,
      equityNet: tradeStats(equityTrades).net,
      symbols: symbolBreakdown(optionTrades),
      equitySymbols: symbolBreakdown(equityTrades),
      today,
      // YTD: the months shown run through the current one (this year) or
      // December (a past year).
      lastMonth: isCurrentYear ? new Date().getMonth() : 11,
      yearEnd: isCurrentYear ? today : `${report.year}-12-31`,
    }
  }, [report])

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
  const openSymbol = (ticker, tab) => openTransactions({ ticker, start: report.start, end: report.end, tab })
  const openMonth = (m) => openTransactions(monthBounds(m))

  // Symbol-by-month table, by source. Transactions shows one tab at a time,
  // so a click opens the tab holding that cell's trades (for "All": options
  // when the symbol had any that month, else equity & futures).
  const heatTrades = !derived ? [] :
    heatSource === 'options' ? derived.optionTrades :
    heatSource === 'equity' ? derived.equityTrades :
    [...derived.optionTrades, ...derived.equityTrades]
  const monthOfTrade = (t) => utcDate(t.close_date).getUTCMonth()
  const heatTab = (ticker, m) => {
    if (heatSource !== 'all') return heatSource === 'equity' ? 'equity' : undefined
    const hasOptions = derived.optionTrades.some((t) => monthOfTrade(t) === m && (ticker == null || (t.underlying_symbol ?? t.symbol) === ticker))
    return hasOptions ? undefined : 'equity'
  }
  const openHeatCell = (ticker, m) => openTransactions({ ticker, ...monthBounds(m), tab: heatTab(ticker, m) })
  const openHeatMonth = (m) => openTransactions({ ...monthBounds(m), tab: heatTab(null, m) })

  const noData = derived && derived.optionTrades.length === 0 && derived.equityTrades.length === 0

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

      {derived && !noData && !loading && report.period === 'month' && (
        <>
          <KpiStrip
            stats={derived.stats}
            prev={derived.prevStats}
            prevName={report.prevName}
            extraNet={derived.equityNet}
          />

          {derived.optionTrades.length > 0 && (
            <div className="report-row">
              <div className="card">
                <div className="report-card-head">
                  <h3 className="section-title">{monthName(report.month)} calendar</h3>
                  <span className="report-card-note">Option P&amp;L by trading day · click a day or week</span>
                </div>
                <MonthCalendar
                  year={report.year}
                  month={report.month}
                  trades={derived.optionTrades}
                  today={derived.today}
                  onDay={openDay}
                  onWeek={openWeek}
                />
              </div>

              <div className="card">
                <div className="report-card-head">
                  <h3 className="section-title">Running total</h3>
                  <span className="report-card-note">Click a day to open its transactions</span>
                </div>
                <div className="report-legend">
                  <span><i className="report-key-bar" style={{ background: 'var(--success)' }} /><i className="report-key-bar" style={{ background: 'var(--error)' }} />Daily P&amp;L</span>
                  <span><i className="report-key-line" />Running total</span>
                </div>
                <DailyRunChart trades={derived.optionTrades} onDay={openDay} />
              </div>
            </div>
          )}

          {derived.symbols.length > 0 && (
            <div className="card">
              <div className="report-card-head">
                <h3 className="section-title">Options by symbol</h3>
                <span className="report-card-note">Click a row to open its transactions</span>
              </div>
              <SymbolTable rows={derived.symbols} onSymbol={(s) => openSymbol(s)} />
            </div>
          )}
        </>
      )}

      {derived && !noData && !loading && report.period === 'ytd' && (
        <>
          <KpiStrip
            stats={derived.stats}
            netNote={(() => {
              const months = Array.from({ length: derived.lastMonth + 1 }, (_, m) =>
                tradeStats(derived.optionTrades.filter((t) => utcDate(t.close_date).getUTCMonth() === m)))
              const traded = months.filter((s) => s.n > 0)
              return `${traded.filter((s) => s.net > 0).length} of ${traded.length} months positive`
            })()}
            extraNet={derived.equityNet}
          />

          {derived.optionTrades.length > 0 && (
            <>
              <div className="report-row report-row--even">
                <div className="card">
                  <div className="report-card-head">
                    <h3 className="section-title">Monthly option P&amp;L</h3>
                    <span className="report-card-note">Click a month to open its transactions</span>
                  </div>
                  <MonthlyBarsChart
                    trades={derived.optionTrades}
                    lastMonth={derived.lastMonth}
                    partialNote={report.year === currentYear() ? 'to date' : null}
                    onMonth={openMonth}
                  />
                </div>
                <div className="card">
                  <div className="report-card-head">
                    <h3 className="section-title">Running total</h3>
                    <span className="report-card-note">Cumulative option P&amp;L</span>
                  </div>
                  <CumulativeChart trades={derived.optionTrades} />
                </div>
              </div>

              <div className="card">
                <div className="report-card-head">
                  <h3 className="section-title">Symbol by month</h3>
                  <span className="report-card-note">Click a cell for that symbol&apos;s trades that month</span>
                </div>
                <div className="tab-row report-source-tabs" role="tablist" aria-label="Trades to include">
                  {[
                    { id: 'options', label: 'Options' },
                    { id: 'equity', label: 'Equity & futures' },
                    { id: 'all', label: 'All' },
                  ].map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      role="tab"
                      aria-selected={heatSource === t.id}
                      className={`tab-item ${heatSource === t.id ? 'active' : ''}`}
                      onClick={() => setHeatSource(t.id)}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
                {heatTrades.length > 0 ? (
                  <SymbolMonthHeat
                    trades={heatTrades}
                    lastMonth={derived.lastMonth}
                    onCell={openHeatCell}
                    onMonth={openHeatMonth}
                  />
                ) : (
                  <p className="summary-line">No equity or futures trades closed in {report.year}.</p>
                )}
                {heatSource === 'all' && heatTrades.length > 0 && (
                  <p className="report-footnote">
                    Options and equity &amp; futures combined by symbol, so an exercised futures option&apos;s premium
                    and the delivered future&apos;s result share one row.
                  </p>
                )}
              </div>

              <div className="card">
                <div className="report-card-head">
                  <h3 className="section-title">Every trading day</h3>
                  <span className="report-card-note">Click a day to open its transactions</span>
                </div>
                <YearCalendar year={report.year} trades={derived.optionTrades} endIso={derived.yearEnd} onDay={openDay} />
              </div>
            </>
          )}
        </>
      )}

      {derived && !noData && !loading && derived.equitySymbols.length > 0 && (
        <div className="card">
          <div className="report-card-head">
            <h3 className="section-title">Equity &amp; futures by symbol</h3>
            <span className="report-card-note">Click a row to open its transactions</span>
          </div>
          <SymbolTable rows={derived.equitySymbols} onSymbol={(s) => openSymbol(s, 'equity')} />
        </div>
      )}
    </div>
  )
}
