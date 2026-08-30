import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip as BarTooltip, Legend as BarLegend, ResponsiveContainer, LabelList,
} from 'recharts'
import { getAllocations, getEquityTransactions } from '../api/client'
import Spinner from '../components/Spinner'
import DataTable from '../components/DataTable'

const COLORS = [
  '#1a56db', '#059669', '#d97706', '#dc2626', '#7c3aed',
  '#0891b2', '#db2777', '#65a30d', '#ea580c', '#0284c7',
]

const SUMMARY_COLUMNS = [
  { key: 'symbol', label: 'Symbol' },
  { key: 'amount', label: 'Amount ($)' },
  { key: 'percent', label: 'Percent (%)' },
]

// Shared by the option and equity/future per-symbol charts — identical shape,
// just different data/total/click destination.
function SymbolProfitChart({ title, label, data, total, onBarClick }) {
  if (data.length === 0) return null
  return (
    <div className="card chart-card">
      <h3 className="section-title">
        {title} — {label}
        <span className="chart-total"> (${total.toLocaleString('en-US', { minimumFractionDigits: 2 })})</span>
      </h3>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="name" tick={{ fontSize: 12 }} />
          <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 12 }} />
          <BarTooltip formatter={(v) => `$${v.toLocaleString('en-US', { minimumFractionDigits: 2 })}`} />
          <Bar dataKey="value" cursor="pointer" onClick={onBarClick}>
            {data.map((r, i) => (
              <Cell key={i} fill={r.value >= 0 ? 'var(--success)' : 'var(--error)'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="chart-caption">Click a bar to view that symbol's transactions for {label}</p>
    </div>
  )
}

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

// Jan 1 through today (or Dec 31 for a past year).
function ytdRange(year) {
  const start = `${year}-01-01`
  const end = year === currentYear() ? new Date().toISOString().split('T')[0] : `${year}-12-31`
  return { start, end }
}

// Aggregate a list of transactions by symbol, summing total_amount per symbol.
function aggregateBySymbol(data) {
  const bySymbol = {}
  for (const row of data) {
    const sym = row.underlying_symbol ?? row.symbol ?? 'OTHER'
    bySymbol[sym] = (bySymbol[sym] ?? 0) + (row.total_amount ?? 0)
  }
  const agg = Object.entries(bySymbol)
    .filter(([, v]) => v !== 0)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
  const tot = agg.reduce((s, r) => s + r.value, 0)
  // Gains and losses can't share one "% of total" — a losing symbol next to
  // winners can make percentages exceed 100% or go negative. Instead express
  // each symbol as a share of gross gains, so losers show as negative drag.
  const grossGains = agg.reduce((s, r) => s + (r.value > 0 ? r.value : 0), 0)
  const tableData = agg.map((r) => ({
    symbol: r.name,
    amount: r.value,
    percent: grossGains !== 0 ? (r.value / grossGains) * 100 : 0,
  }))
  return { agg, tot, tableData }
}

// Resolve a date to its ISO week number plus that week's Mon–Sun date range
function isoWeekRange(dateStr) {
  const d = new Date(dateStr)
  const jan4 = new Date(d.getFullYear(), 0, 4)
  const startOfWeek1 = new Date(jan4)
  startOfWeek1.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7))
  const week = Math.floor((d - startOfWeek1) / (7 * 24 * 3600 * 1000)) + 1
  const start = new Date(startOfWeek1)
  start.setDate(start.getDate() + (week - 1) * 7)
  const end = new Date(start)
  end.setDate(end.getDate() + 6)
  const fmt = (dt) => dt.toISOString().split('T')[0]
  return { week, start: fmt(start), end: fmt(end) }
}

export default function ProfitLoss() {
  const navigate = useNavigate()
  const [period, setPeriod] = useState('month') // 'month' | 'ytd'
  const [year, setYear] = useState(currentYear)
  const [month, setMonth] = useState(currentMonth)
  const [realizedOnly, setRealizedOnly] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [submitted, setSubmitted] = useState(false)
  const [symbolData, setSymbolData] = useState([])
  const [weeklyData, setWeeklyData] = useState([])
  const [tableData, setTableData] = useState([])
  const [total, setTotal] = useState(0)
  const [equitySymbolData, setEquitySymbolData] = useState([])
  const [equityTableData, setEquityTableData] = useState([])
  const [equityTotal, setEquityTotal] = useState(0)
  const [label, setLabel] = useState('')

  const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear() - i)

  function currentRange() {
    return period === 'ytd' ? ytdRange(year) : monthRange(year, month)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setSubmitted(false)
    try {
      const { start, end } = currentRange()
      const [data, equityData] = await Promise.all([
        getAllocations(start, end, realizedOnly),
        getEquityTransactions('', start, end, 'ALL', realizedOnly),
      ])
      setLabel(period === 'ytd' ? `YTD ${year}` : `${monthName(month)} ${year}`)

      if (equityData && equityData.length > 0) {
        const { agg, tot, tableData: equityRows } = aggregateBySymbol(equityData)
        setEquitySymbolData(agg)
        setEquityTotal(tot)
        setEquityTableData(equityRows)
      } else {
        setEquitySymbolData([]); setEquityTotal(0); setEquityTableData([])
      }

      if (!data || data.length === 0) {
        setSymbolData([]); setWeeklyData([]); setTableData([]); setTotal(0)
        setSubmitted(true)
        return
      }

      const { agg, tot, tableData: optionRows } = aggregateBySymbol(data)
      setSymbolData(agg)
      setTotal(tot)
      setTableData(optionRows)

      // Weekly grouped bar chart
      const weekMap = {} // { week: { sym: amount } }
      const weekRanges = {} // { week: { start, end } }
      for (const row of data) {
        if (!row.close_date) continue
        const { week: weekNum, start: weekStart, end: weekEnd } = isoWeekRange(row.close_date)
        const week = `W${weekNum}`
        weekRanges[week] = { start: weekStart, end: weekEnd }
        const sym = row.underlying_symbol ?? row.symbol ?? 'OTHER'
        if (!weekMap[week]) weekMap[week] = {}
        weekMap[week][sym] = (weekMap[week][sym] ?? 0) + (row.total_amount ?? 0)
      }
      const allSymbols = [...new Set(data.map((r) => r.underlying_symbol ?? r.symbol ?? 'OTHER'))]
      const weekly = Object.entries(weekMap)
        .sort(([a], [b]) => Number(a.slice(1)) - Number(b.slice(1)))
        .map(([week, syms]) => {
          const total = Object.values(syms).reduce((s, v) => s + v, 0)
          // "zero" is a zero-height bar stacked on top of the real ones, purely so
          // its LabelList renders the week's total right at the top of the stack.
          return { week, ...syms, total, zero: 0 }
        })
      setWeeklyData({ rows: weekly, symbols: allSymbols, ranges: weekRanges })
      setSubmitted(true)
    } catch (err) {
      setSymbolData([]); setWeeklyData([]); setTableData([]); setTotal(0)
      setEquitySymbolData([]); setEquityTotal(0); setEquityTableData([])
      const msg = err?.message ?? ''
      if (msg.toLowerCase().includes('token') || msg.toLowerCase().includes('auth')) {
        setError('Broker authentication failed — the Schwab refresh token has expired. Please re-authenticate.')
      } else {
        setError('Failed to fetch allocation data. Make sure the API server is running.')
      }
    } finally {
      setLoading(false)
    }
  }

  const noData = submitted && symbolData.length === 0 && equitySymbolData.length === 0

  function handleBarClick(row, tab) {
    const symbol = row?.name ?? row?.payload?.name
    if (!symbol) return
    const { start, end } = currentRange()
    const params = new URLSearchParams({ ticker: symbol, start, end, realized: String(realizedOnly) })
    if (tab) params.set('tab', tab)
    navigate(`/transactions?${params}`)
  }

  function handleWeekBarClick(symbol, data) {
    const week = data?.week ?? data?.payload?.week
    const range = week && weeklyData.ranges?.[week]
    if (!range) return
    const params = new URLSearchParams({ ticker: symbol, start: range.start, end: range.end, realized: String(realizedOnly) })
    navigate(`/transactions?${params}`)
  }

  // Clicking the week label itself (rather than one symbol's bar) shows every
  // symbol's transactions for that week.
  function handleWeekLabelClick(week) {
    const range = weeklyData.ranges?.[week]
    if (!range) return
    const params = new URLSearchParams({ start: range.start, end: range.end, realized: String(realizedOnly) })
    navigate(`/transactions?${params}`)
  }

  function WeekAxisTick({ x, y, payload }) {
    return (
      <text
        x={x}
        y={y + 12}
        textAnchor="middle"
        fontSize={12}
        fill="var(--primary)"
        cursor="pointer"
        onClick={() => handleWeekLabelClick(payload.value)}
      >
        {payload.value}
      </text>
    )
  }

  // Default Tooltip would also list the invisible "zero" anchor bar — filter it out.
  function WeeklyTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null
    const visible = payload.filter((p) => p.dataKey !== 'zero')
    return (
      <div style={{ background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px', boxShadow: 'var(--shadow-sm)' }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>{label}</div>
        {visible.map((p) => (
          <div key={p.dataKey} style={{ color: p.color, fontSize: '0.85rem' }}>
            {p.name}: ${Number(p.value).toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="page">
      <h2 className="page-title">Profit/Loss</h2>

      <div className="button-row">
        <button
          type="button"
          className={`btn ${period === 'month' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setPeriod('month')}
        >
          Month
        </button>
        <button
          type="button"
          className={`btn ${period === 'ytd' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setPeriod('ytd')}
        >
          YTD
        </button>
      </div>

      <div className="card">
        <form onSubmit={handleSubmit}>
          <div className="form-row form-row--2">
            <div className="form-group">
              <label>Year</label>
              <select value={year} onChange={(e) => setYear(Number(e.target.value))} className="input">
                {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
            {period === 'month' && (
              <div className="form-group">
                <label>Month</label>
                <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="input">
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                    <option key={m} value={m}>{monthName(m)}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
          <div className="form-actions">
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={realizedOnly}
                onChange={(e) => setRealizedOnly(e.target.checked)}
                className="toggle-checkbox"
              />
              <span>Realized Gains Only</span>
            </label>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              Submit
            </button>
          </div>
        </form>
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <Spinner />}

      {noData && !loading && (
        <div className="alert warning">No transaction data available for this month.</div>
      )}

      {submitted && !loading && (symbolData.length > 0 || equitySymbolData.length > 0) && (
        <>
          <div className="charts-row">
            <SymbolProfitChart
              title="Option Trade Profit"
              label={label}
              data={symbolData}
              total={total}
              onBarClick={(row) => handleBarClick(row)}
            />
            <SymbolProfitChart
              title="Equity/Future Profit"
              label={label}
              data={equitySymbolData}
              total={equityTotal}
              onBarClick={(row) => handleBarClick(row, 'equity')}
            />

            {/* Weekly bar chart — spans the full row width, below the per-symbol charts */}
            {weeklyData.rows?.length > 0 && (
              <div className="card chart-card chart-card--full">
                <h3 className="section-title">Weekly Allocation — {label}</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={weeklyData.rows} margin={{ top: 24, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="week" tick={<WeekAxisTick />} />
                    <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 12 }} />
                    <BarTooltip content={<WeeklyTooltip />} />
                    <BarLegend />
                    {weeklyData.symbols.map((sym, i) => (
                      <Bar
                        key={sym}
                        dataKey={sym}
                        stackId="week"
                        fill={COLORS[i % COLORS.length]}
                        cursor="pointer"
                        onClick={(data) => handleWeekBarClick(sym, data)}
                      />
                    ))}
                    {/* Zero-height bar stacked on top, just to anchor a label showing the week's total */}
                    <Bar dataKey="zero" stackId="week" fill="transparent" legendType="none" isAnimationActive={false}>
                      <LabelList
                        dataKey="total"
                        position="top"
                        formatter={(v) => `$${v.toLocaleString('en-US', { maximumFractionDigits: 0 })}`}
                        style={{ fontSize: 12, fontWeight: 600, fill: 'var(--text)' }}
                      />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <p className="chart-caption">Click a bar for that symbol's transactions that week, or the week label for all transactions that week</p>
              </div>
            )}
          </div>

          {/* Summary tables */}
          {tableData.length > 0 && (
            <div className="card">
              <h3 className="section-title">Option Trade Summary</h3>
              <DataTable data={tableData} columns={SUMMARY_COLUMNS} defaultSortKey="amount" />
            </div>
          )}

          {equityTableData.length > 0 && (
            <div className="card">
              <h3 className="section-title">Equity/Future Summary</h3>
              <DataTable data={equityTableData} columns={SUMMARY_COLUMNS} defaultSortKey="amount" />
            </div>
          )}
        </>
      )}
    </div>
  )
}
